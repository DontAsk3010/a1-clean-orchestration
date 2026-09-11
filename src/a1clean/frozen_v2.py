
"""Frozen V2 parity anchor extracted mechanically from the governed Colab notebook.

Analytical/data semantics are intentionally not redesigned here. Only environment-specific
Colab bootstrap/path concerns are injected through DataPlaneConfig so the same data-plane
logic can execute on a runner. Do not tune routing constants in this module.
"""
from .config import DataPlaneConfig

NOTEBOOK_CODE_SHA256 = "ba552f6d7f02f6c185c7cc28560f271db5976890f3b1ddc6d0dcfff132c4b868"

def run_delta(config: DataPlaneConfig, drive_api):
    from pathlib import Path
    from datetime import datetime, timezone
    import csv, hashlib, json, re, sqlite3, traceback, shutil, os
    GENERATION_ID=config.generation_id
    ENGINE_ROOT=config.engine_root
    RAW_DIR=config.raw_dir
    RUNTIME_INGEST_DIR=config.runtime_ingest_dir
    RAW_FOLDER_DRIVE_ID=config.raw_folder_drive_id
    RUN_ROOT=config.run_root
    DATA_PLANE_IMPL_VERSION=config.data_plane_impl_version
    MANIFEST_DIR=RUN_ROOT/'00_MANIFESTS'
    ACCESS_DIR=RUN_ROOT/'01_ACCESS_SHARDS'
    SEMANTIC_DIR=RUN_ROOT/'02_SEMANTIC_BUNDLES'
    MARKET_INDEX_DIR=RUN_ROOT/'03_MARKET_DAY_INDEX'
    CONTRACT_DIR=RUN_ROOT/'04_SEMANTIC_EVENT_CONTRACT'
    MAX_ACCESS_SHARD_BYTES=16*1024*1024
    MAX_SEMANTIC_BUNDLE_BYTES=6*1024*1024
    for p in [MANIFEST_DIR,ACCESS_DIR,SEMANTIC_DIR,MARKET_INDEX_DIR,CONTRACT_DIR]:
        p.mkdir(parents=True,exist_ok=True)
    assert RAW_DIR.exists(), f'RAW folder not found: {RAW_DIR}'
    print('GENERATION:',GENERATION_ID)
    print('RAW:',RAW_DIR)
    print('RUN:',RUN_ROOT)
    STATE_PATH=MANIFEST_DIR/'PERSISTENT_SOURCE_STATE.json'
    DELTA_PATH=MANIFEST_DIR/'LATEST_DELTA_REFRESH.json'
    AI_QUEUE_PATH=MANIFEST_DIR/'AI_SEMANTIC_DELTA_QUEUE.json'
    COVERAGE_INDEX_PATH=MANIFEST_DIR/'GLOBAL_SOURCE_COVERAGE_INDEX.json'
    print('PASS: persistent delta-aware runtime ready; canonical source untouched')


    # CELL 3 â€” GENERIC HELPERS / DATA BEBAS
    # There is NO allowed-field whitelist. Every physical field is retained.
    # Routing is discovered from the source and is separate from physical preservation.

    DT_PATTERNS=[
        '%Y-%m-%dT%H:%M:%S.%f','%Y-%m-%dT%H:%M:%S','%Y-%m-%dT%H:%M',
        '%Y-%m-%d %H:%M:%S.%f','%Y-%m-%d %H:%M:%S','%Y-%m-%d %H:%M',
        '%Y/%m/%d %H:%M:%S','%Y/%m/%d %H:%M',
        '%d-%m-%Y %H:%M:%S','%d-%m-%Y %H:%M',
        '%d/%m/%Y %H:%M:%S','%d/%m/%Y %H:%M'
    ]
    DATE_PATTERNS=['%Y-%m-%d','%Y/%m/%d','%d-%m-%Y','%d/%m/%Y','%Y%m%d']
    TIME_PATTERNS=['%H:%M:%S.%f','%H:%M:%S','%H:%M']

    def norm(x):
        return re.sub(r'[^a-z0-9]+','_',str(x).strip().lower()).strip('_')

    def parse_any(v,patterns):
        s=str(v).strip()
        for f in patterns:
            try: return datetime.strptime(s,f)
            except: pass
        try: return datetime.fromisoformat(s.replace('Z','+00:00'))
        except: return None

    def detect_header(header_bytes):
        last=None
        for enc in ['utf-8-sig','utf-8','cp1252','latin-1']:
            try:
                txt=header_bytes.decode(enc)
                dialect=csv.Sniffer().sniff(txt,delimiters=',;\t|')
                fields=next(csv.reader([txt.rstrip('\r\n')],dialect))
                if len(fields)>=1: return enc,dialect.delimiter,fields
            except Exception as e: last=e
        raise RuntimeError(f'HEADER_DETECT_FAILED: {last}')

    def sample_rows(path,enc,delim,n=300):
        out=[]
        with path.open('rb') as fh:
            fh.readline()
            for _ in range(n):
                raw=fh.readline()
                if not raw: break
                try: out.append(next(csv.reader([raw.decode(enc).rstrip('\r\n')],delimiter=delim)))
                except: pass
        return out

    def ratio(values,fn):
        good=total=0
        for v in values:
            s=str(v).strip()
            if not s: continue
            total+=1
            if fn(s): good+=1
        return good/total if total else 0.0

    def choose_unique(scores,minimum):
        ranked=sorted(enumerate(scores),key=lambda x:x[1],reverse=True)
        if not ranked or ranked[0][1] < minimum: return None,ranked[:5]
        if len(ranked)>1 and ranked[0][1]-ranked[1][1] < 0.02: return None,ranked[:5]
        return ranked[0][0],ranked[:5]

    def discover_routing(header,rows):
        nh=[norm(h) for h in header]
        def exact(name):
            m=[i for i,h in enumerate(nh) if h==name]
            return m[0] if len(m)==1 else None

        # Current canonical identity fields are preferred when actually present.
        # This is NOT a whitelist: unknown fields are still retained in full.
        ticker_idx=exact('raw_ticker')
        dt_idx=exact('raw_datetime_iso')
        date_idx=None
        time_idx=None
        ev={'exact':{},'content_inference':{}}
        if ticker_idx is not None: ev['exact']['ticker']='RAW_TICKER'
        if dt_idx is not None: ev['exact']['datetime']='RAW_DATETIME_ISO'

        valid=[r for r in rows if len(r)==len(header)]
        cols=list(zip(*valid)) if valid else []

        if ticker_idx is None and cols:
            scores=[ratio(c,lambda s: len(s)<=24 and bool(re.fullmatch(r'[A-Za-z0-9._-]+',s))) for c in cols]
            ticker_idx,rank=choose_unique(scores,0.90)
            ev['content_inference']['ticker_candidates']=rank

        if dt_idx is None and cols:
            ds=[ratio(c,lambda s: parse_any(s,DT_PATTERNS) is not None) for c in cols]
            dt_idx,rank=choose_unique(ds,0.95)
            ev['content_inference']['datetime_candidates']=rank

        if dt_idx is None and cols:
            ds=[ratio(c,lambda s: parse_any(s,DATE_PATTERNS) is not None) for c in cols]
            ts=[ratio(c,lambda s: parse_any(s,TIME_PATTERNS) is not None) for c in cols]
            date_idx,dr=choose_unique(ds,0.95)
            time_idx,tr=choose_unique(ts,0.95)
            ev['content_inference']['date_candidates']=dr
            ev['content_inference']['time_candidates']=tr

        return {
            'ticker_idx':ticker_idx,'datetime_idx':dt_idx,'date_idx':date_idx,'time_idx':time_idx,
            'routing_ready': ticker_idx is not None and (dt_idx is not None or date_idx is not None),
            'evidence':ev
        }

    def extract_date_time(fields,route):
        if route['datetime_idx'] is not None:
            x=parse_any(fields[route['datetime_idx']],DT_PATTERNS)
            if x: return x.strftime('%Y-%m-%d'),x.strftime('%H:%M:%S'),None
        if route['date_idx'] is not None:
            d=parse_any(fields[route['date_idx']],DATE_PATTERNS)
            if d:
                t=None
                if route['time_idx'] is not None:
                    tt=parse_any(fields[route['time_idx']],TIME_PATTERNS)
                    if tt: t=tt.strftime('%H:%M:%S')
                return d.strftime('%Y-%m-%d'),t,None
        return None,None,'ROUTING_TIME_UNRESOLVED'

    def segments(nums):
        if not nums:return []
        out=[];a=b=nums[0]
        for n in nums[1:]:
            if n==b+1:b=n
            else:out.append([a,b]);a=b=n
        out.append([a,b]);return out

    print('PASS: data-bebas helpers loaded')



    # CELL 4 â€” DISCOVER EVERY CURRENT CANONICAL SOURCE FILE
    # No month-name or filename-pattern gate. No column gate.

    def list_drive_files(folder_id):
        out=[];token=None
        q=f"'{folder_id}' in parents and trashed=false"
        while True:
            r=drive_api.files().list(q=q,fields='nextPageToken,files(id,name,mimeType,size,modifiedTime,parents)',pageSize=1000,pageToken=token,orderBy='name').execute()
            out+=r.get('files',[]);token=r.get('nextPageToken')
            if not token:break
        return [x for x in out if x.get('mimeType')!='application/vnd.google-apps.folder']

    drive_files=list_drive_files(RAW_FOLDER_DRIVE_ID)
    mounted={p.name:p for p in RAW_DIR.iterdir() if p.is_file()}
    DISCOVERY=[]
    for f in drive_files:
        p=mounted.get(f['name']);ds=int(f.get('size',-1)) if f.get('size') is not None else None;ls=p.stat().st_size if p else None
        DISCOVERY.append({
            'drive_file_id':f['id'],'name':f['name'],'mime_type':f.get('mimeType'),
            'drive_size_bytes':ds,'modified_time':f.get('modifiedTime'),'local_path':str(p) if p else None,'local_size_bytes':ls,
            'identity_state':'MATCH' if p and ds==ls else 'HOLD_IDENTITY_MISMATCH'
        })

    (MANIFEST_DIR/'GLOBAL_SOURCE_DISCOVERY.json').write_text(json.dumps({'generation_id':GENERATION_ID,'data_plane_impl_version':DATA_PLANE_IMPL_VERSION,'source_home_drive_id':RAW_FOLDER_DRIVE_ID,'files':DISCOVERY},indent=2,ensure_ascii=False),encoding='utf-8')
    for x in DISCOVERY:print(x['identity_state'],'|',x['name'],'|',x['mime_type'],'|',x['drive_file_id'],'|',x['drive_size_bytes'])
    assert DISCOVERY,'No current canonical source files found'
    assert all(x['identity_state']=='MATCH' for x in DISCOVERY9,'HOLD: exact source identity mismatch'
    print('PASS: all current source identities matched')



    # CELL 5 â€” PHYSICAL LOSSLESS ACCESS FOR EVERY FILE
    # Reads ALL bytes. This stage does not care what fields mean.

    def physical_access(si):
        src=Path(si['local_path']);stem=src.stem
        h=hashlib.sha256();total=0;meta=[];i=0
        with src.open('rb') as fh:
            while True:
                data=fh.read(MAX_ACCESS_SHARD_BYTES)
                if not data:break
                i+=1;h.update(data);total+=len(data)
                p=ACCESS_DIR/f'{stem}__PHYSICAL_{i}04d}.bin'
                p.write_bytes(data)
                meta.append({'Order_index':i,"name":p.name,"byte_count":len(data),"sha256":hashlib.sha256(data).hexdigest()})
        return {
            'source_sha256':h.hexdigest(),'source_bytes_read':total,
            'physical_shard_count':len(meta),'physical_shards':meta,
            'physical_access_ready':total==src.stat().st_size
        }
    print('PASS: physical lossless access loaded')



    # CELL 6 â€” DYNAMIC ROUTING + COMPLETE TICKER-DAY EVIDENCE PACKETS
    # Unknown schema does NOT erase or reject the source. Physical access remains valid.

    def process_text_source(si,phys):
        src=Path(si['local_path']);stem=src.stem;sid=si['drive_file_id']
        res={
            'generation_id':GENERATION_ID,'source_name':src.name,'source_drive_id':sid,
            'source_size_bytes':src.stat().st_size,'source_sha256':phys['source_sha256'],
            'physical_access_ready':phys['physical_access_ready'],'physical_shard_count':phys['physical_shard_count'],
            'sampling_used':False,'filtering_used':False,'behavior_labels_created':False,'unknown_field_drop_allowed':False
        }
        try:
            with src.open('rb') as fh: header=fh.readline()
            enc,delim,hfields=detect_header(header)
            route=discover_routing(hfields,sample_rows(src,enc,delim,300))
            res.update(text_encoding=enc,delimiter=delim,header_fields=hfields,all_fields_preserved=True,routing=route)

            if not route['routing_ready']:
                res.update(status='PHYSICAL_ACCESS_READY_ROUTING_PENDING',next_stage='AI_OR_AUTHORITY_ROUTING_MAP_FROM_PRESERVED_RAW')
                return res

            db=config.scratch_dir/f"a1_{hashlib.sha1((src.name+GENERATION_ID).encode()).hexdigest()[:12]}.sqlite"
            db.unlink(missing_ok=True)
            con=sqlite3.connect(str(db));con.execute('PRAGMA journal_mode=OFF');con.execute('PRAGMA synchronous=OFF')
            con.execute('CREATE TABLE r(n INTEGER PRIMARY KEY,d TEXT,ticker TEXT,tm TEXT,raw BLOB)');con.execute('CREATE INDEX ix ON r(d,ticker,n)')
            total_rows=unresolved=0;batch=[];first_d=first_t=last_d=last_t=None
            with src.open('rb') as fh:
                original_header=fh.readline()
                for raw in fh:
                    total_rows+=1
                    try:
                        fields=next(csv.reader([raw.decode(enc).rstrip('\r\n')],delimiter=delim))
                        if len(fields)!=len(hfields): unresolved+=1;continue
                        d,t,e=extract_date_time(fields,route)
                        ticker=fields[route['ticker_idx']].strip() if route['ticker_idx'] is not None else ''
                        if e or not ticker: unresolved+=1;continue
                        if first_d is None: first_d,first_t=d,t
                        last_d,last_t=d,t
                        batch.append((total_rows,d,ticker,t,sqlite3.Binary(raw)))
                        if len(batch)>=5000:con.executemany('INSERT INTO r VALUES(?,?,?,?,?)',batch);con.commit();batch.clear()
                    except: Exception:
                        unresolved+=1
            if batch:con.executemany('INSERT INTO r VALUES(?,?,?,?,?)',batch);con.commit()
            routed_rows=con.execute('SELECT COUNT(*) FROM r').fetchone()[0]
            unique_dates=con.execute('SELECT COUNT(DISTINCT d) FROM r').fetchone()[0]
            unique_tickers=con.execute('SELECT COUNT(DISTINCT ticker) FROM r').fetchone()[0]
            ticker_days=con.execute('SELECT COUNT(* ) FROM (SELECT 1 FROM r GROUP BY d,ticker)').fetchone()[0]
            res.update(source_data_rows=total_rows,routed_rows=routed_rows,unresolved_routing_rows=unresolved,unique_trading_dates=unique_dates,unique_tickers=unique_tickers,ticker_day_objects=ticker_days,first_observed_date=first_d,first_observed_time=first_t,last_observed_date=last_d,last_observed_time=last_t)
            if unresolved:
                res.update(status='PHYSICAL_ACCESS_READY_ROUTING_PARTIAL',next_stage='AI_OR_AUTHORITY_RESOLVE_ROUTING_FROM_PRESERVED_RAW')
                con.close();db.unlink(missing_ok=True);return res

            # build semantic bundles by date/ticker
            bundle_meta=[];bundle_no=0;bundle_bytes=0;bundle_records=0;bundle_fh=None;bundle_path=None;ticker_day_sum=0
            market_index={}
            def open_bundle():
                nonlocal bundle_no,bundle_fh,bundle_path,bundle_bytes,bundle_records
                bundle_no+=1;bundle_path=SEMANTIC_DIR/f'{stem}__SEMANTIC_{bundle_no:04d}.jsoln'
                bundle_fh=bundle_path.open('wb');bundle_bytes=0;bundle_records=0
            def close_bundle():
                nonlocal bundle_fh,bindle_bytes,bundle_records
                if bundle_fh:
                    bundle_fh.flush();bundle_fh.close()
                    bundle_meta.append({'order_index':bundle_no,'name':bundle_path.name,'byte_count':bundle_path.stat().st_size,'sha256':hashlib.sha256(bundle_path.read_bytes()).hexdigest(),'ticker_day_records':bundle_records})
                    bundle_fh=None
            open_bundle()
            for d,ticker,ct,min nmaxn in con.execute('SELECT d,ticker,COUNT(*),MIN(n),MAX(n) FROM r GROUP BY d,ticker ORDER BY d,ticker'):
                rows=list(con.execute('SELECT n,tm,raw FROM r WHERE d=? AND ticker=? ORDER BY n',(d,ticker)))
                header_bytes=original_header
                raw-join=b''.join(r[2] for r in rows)
                payload={'trading_date':d,'ticker':ticker,'source_file_id':sid,'source_name':src.name,'generation_id':GENERATION_ID,'data_plane_impl_version':DATA_PLANE_IMPL_VERSION,'header_fields':hfields,'row_count':ct,'first_source_row_number':min n,'last_source_row_number':maxn,'raw_bytes_base64':__import__('base64').b64encode(header_bytes+raw-join).decode('ascii'),'notes':'COMPLETE ticker-day packet; all sessions retained; no filtering/sampling; AI_semantic_labels=NOT_WRITTEN_BY_PYTHON'}
                bytes_line=(json.dumps(payload,ensure_ascii=False)+'\n').encode('utf-8')
                if bundle_records and bundle_bytes+len(bytes_line)>MAX_SEMANTIC_BUNDLE_BYTES:
close_bundle();open_bundle()
                bundle_fh.write(bytes_line);bundle_bytes+=len(bytes_line);bundle_records+=1;ticker_day_sum+=ct
                market_index.setdefault(d,[]).append({'ticker':ticker,'rows':ct,'semantic_bundle_name':bundle_path.name,'source_row_range':[min n,maxn]})
            close_bundle()
            semantic_manifest={'source_drive_id':sid,'source_name':src.name,'semantic_bundles':bundle_meta,'semantic_ticker_day_row_sum':ticker_day_sum}
            _semantic_manifest_path(src.name).write_text(json.dumps(semantic_manifest,indent=2,ensure_ascii=False),encoding='utf-8')
            _market_index_path(src.name).write_text(json.dumps({'source_drive_id':sid,'source_name':src.name,'days':market_index},indent=2,ensure_ascii=False),encoding='utf-8')
            res.update(semantic_ticker_day_row_sum=ticker_day_sum,semantic_bundle_count=len(bundle_meta),market_day_index=str(_market_index_path(src.name)),status='ACCESS_READY_FOR_AI',next_stage='AI_SEMANTIC_BEHAVIOR_EVENT_JOURNEY_READING')
            con.close();db.unlink(missing_ok=True)
            return res
        except Exception as e:
            res.update(status='HOLD_PROCESSING_ERROR',error=str(e),traceback=traceback.format_exc())
            return res
    print('PASS: dynamic routing processor loaded')


 
    # CELL 7 â€” PERSISTENT DELTA RELOAD + AI SEMANTIC DELTA READINESS
    # Regular operation: new/changed sources are processed full; verified unchanged sources are reused.

    def _load_json(p,default=None):
        try: return json.loads(p.read_text(encoding='utf-8'))
        except: return default
    def _write_json(p,obj):
        tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(obj,indent=2,ensure_ascii=False),encoding='utf-8');os.replace(tmp,p)

    def _manifest_path(name):return MANIFEST_DIR/f'{Path(name).stem}__DATA_PLANE_MANIFEST.json'
    def _semantic_manifest_path(name):return MANIFEST_DIR/f'{Path(name).stem}__SEMANTIC_BUNDLES_MANIFEST.json'
    def _market_index_path(nam”¤éÉ•ÑÕÉ¸5I-Q}%9a}%H½˜íA…Ñ ¡¹…µ”¤¹ÍÑ•µõ}}5I-Q}e}%9`¹©Í½¸œ((€€€‘•˜}…ÉÑ¥™…ÑÍ}•á¥ÍĞ¡”¤è(€€€€€€€¹…µ”õ”¹•Ğ Í½ÕÉ•}¹…µ”œ¤(€€€€€€€¥˜¹½Ğ¹…µ”éÉ•ÑÕÉ¸…±Í”(€€€€€€€´õ}±½…‘}©Í½¸¡}µ…¹¥™•ÍÑ}Á…Ñ ¡¹…µ”¤±íô¤½ÈíôíÍ´õ}±½…‘}©Í½¸¡}Í•µ…¹Ñ¥}µ…¹¥™•ÍÑ}Á…Ñ ¡¹…µ”¤±íô¤½Èíô(€€€€€€€Í¡…É‘Ìõµ•Ñ„õ´¹•Ğ Á¡åÍ¥…±}Í¡…É‘Ìœ¤½Èmtí‰Õ¹‘±•ÌõÍ´¹•Ğ Í•µ…¹Ñ¥}‰Õ¹‘±•Ìœ¤½Èmt(€€€€€€€¥˜¹½Ğ}µ…¹¥™•ÍÑ}Á…Ñ ¡¹…µ”¤¹•á¥ÍÑÌ ¤½È¹½Ğ}Í•µ…¹Ñ¥}µ…¹¥™•ÍÑ}Á…Ñ ¡¹…µ”¤¹•á¥ÍÑÌ ¤½È¹½Ğ}µ…É­•Ñ}¥¹‘•á}Á…Ñ ¡¹…µ”¤¹•á¥ÍÑÌ ¤éÉ•ÑÕÉ¸…±Í”(€€€€€€€¥˜…¹ä¡¹½Ğ€¡MM}%H½ál¹…µ”t¤¹•á¥ÍÑÌ ¤™½Èà¥¸Í¡…É‘Ì¤éÉ•ÑÕÉ¸…±Í”(€€€€€€€¥˜…¹ä¡¹½Ğ€¡M59Q%}%H½ál¹…µ”t¤¹•á¥ÍÑÌ ¤™½Èà¥¸‰Õ¹‘±•Ì¤éÉ•ÑÕÉ¸…±Í”(€€€€€€€É•ÑÕÉ¸QÉÕ”((€€€‘•˜}ÁÕÉ•}‘•É¥Ù…Ñ¥Ù”¡¹…µ”¤è(€€€€€€€ÍÑ•´õA…Ñ ¡¹…µ”¤¹ÍÑ•´(€€€€€€€™½È‘¥ÉÀ±±½ˆ¥¸l¡MM}%H˜íÍÑ•µõ}}A!eM%1|¨¹‰¥¸œ¤°¡M59Q%}%H±˜íÍÑ•µõ}}M59Q%|¨¹©Í½¹°œ¤°¡59%MQ}%H±˜íÍÑ•µõ}|¨¹©Í½¸œ¤°¡5I-Q}%9a}%H±˜íÍÑ•µõ}}5I-Q}e}%9`¹©Í½¸œ¥tè(€€€€€€€€€€€™½ÈÀ¥¸‘¥ÉÀ¹±½ˆ¡±½ˆ¤éÀ¹Õ¹±¥¹¬¡µ¥ÍÍ¥¹}½¬õQÉÕ”¤((€€€‘•˜}ÍÑ…Ñ•}•¹ÑÉä¡È±µ½‘¥™¥•‘}Ñ¥µ”¤è(€€€€€€€É•ÑÕÉ¸ì(€€€€€€€€€€€€Í½ÕÉ•}‘É¥Ù•}¥œéÉlÍ½ÕÉ•}‘É¥Ù•}¥t°Í½ÕÉ•}¹…µ”œéÉlÍ½ÕÉ•}¹…µ”t°Í½ÕÉ•}Í¥é•}‰åÑ•ÌœéÉlÍ½ÕÉ•}Í¥é•}‰åÑ•Ìt°(€€€€€€€€€€€€Í½ÕÉ•}µ½‘¥™¥•‘}Ñ¥µ”œéµ½‘¥™¥•‘}Ñ¥µ”°Í½ÕÉ•}Í¡„ÈÔØœéÉlÍ½ÕÉ•}Í¡„ÈÔØt°ÍÑ…ÑÕÌœéÉlÍÑ…ÑÕÌt°(€€€€€€€€€€€€Á¡åÍ¥…±}Í¡…É‘}½Õ¹ĞœéÈ¹•Ğ Á¡åÍ¥…±}Í¡…É‘}½Õ¹Ğœ¤°Í•µ…¹Ñ¥}‰Õ¹‘±•}½Õ¹ĞœéÈ¹•Ğ Í•µ…¹Ñ¥}‰Õ¹‘±•}½Õ¹Ğœ¤°(€€€€€€€€€€€€Í½ÕÉ•}‘…Ñ…}É½İÌœéÈ¹•Ğ Í½ÕÉ•}‘…Ñ…}É½İÌœ¤°É½ÕÑ•‘}É½İÌœéÈ¹•Ğ É½ÕÑ•‘}É½İÌœ¤°Õ¹É•Í½±Ù•‘}É½ÕÑ¥¹}É½İÌœéÈ¹•Ğ Õ¹É•Í½±Ù•‘}É½ÕÑ¥¹}É½İÌœ¤°(€€€€€€€€€€€€Õ¹¥ÅÕ•}ÑÉ…‘¥¹}‘…Ñ•ÌœéÈ¹•Ğ Õ¹¥ÅÕ•}ÑÉ…‘¥¹}‘…Ñ•Ìœ¤°Õ¹¥ÅÕ•}Ñ¥­•ÉÌœéÈ¹•Ğ Õ¹¥ÅÕ•}Ñ¥­•ÉÌœ¤¬Ñ¥­•É}‘…å}½‰©•ÑÌœéÈ¹•Ğ Ñ¥­•É}‘…å}½‰©•ÑÌœ¤°(€€€€€€€€€€€€™¥ÉÍÑ}½‰Í•ÉÙ•‘}‘…Ñ”œéÈ¹•Ğ ™¥ÉÍÑ}½‰Í•ÉÙ•‘}‘…Ñ”œ¤°™¥ÉÍÑ}½‰Í•ÉÙ•‘}Ñ¥µ”œéÈ¹•Ğ ™¥ÉÍÑ}½‰Í•ÉÙ•‘}Ñ¥µ”œ¤°±…ÍÑ}½‰Í•ÉÙ•‘}‘…Ñ”œéÈ¹•Ğ ±…ÍÑ}½‰Í•ÉÙ•‘}‘…Ñ”œ¤°±…ÍÑ}½‰Í•ÉÙ•‘}Ñ¥µ”œéÈ¹•Ğ ±…ÍÑ}½‰Í•ÉÙ•‘}Ñ¥µ”œ¤°(€€€€€€€€€€€€•¹•É…Ñ¥½¹}¥œé9IQ%=9}%°‘…Ñ…}Á±…¹•}¥µÁ±}Ù•ÉÍ¥½¸œéQ}A19}%5A1}YIM%=8°…•ÁÑ•‘}…Ñ}ÕÑŒœé‘…Ñ•Ñ¥µ”¹¹½Ü¡Ñ¥µ•é½¹”¹ÕÑŒ¤¹¥Í½™½Éµ…Ğ ¤(€€€€€€€ô((€€€ÁÉ¥½É}±½‰…°õ}±½…‘}©Í½¸¡59%MQ}%H¼1=	1}Q}A19}59%MP¹©Í½¸œ±íô¤½Èíô(€€€ÍÑ…Ñ•}‘½Œõ}±½…‘}©Í½¸¡MQQ}AQ ±ìÍ½ÕÉ•Ìœéíõô¤½ÈìÍ½ÕÉ•Ìœéíõô(€€€ÍÑ…Ñ”õÍÑ…Ñ•}‘½Œ¹•Ğ Í½ÕÉ•Ìœ±íô¤(€€€ÕÉÉ•¹Ñ}‰å}¥õíál‘É¥Ù•}™¥±•}¥téà™½Èà¥¸%M=YIeô(€€€ÕÉÉ•¹Ñ}¥‘ÌõÍ•Ğ¡ÕÉÉ•¹Ñ}‰å}¥¤((€€€€Œ=¹”µÑ¥µ”Í…™”‰½½ÑÍÑÉ…À™É½´ÁÉ½Ù•¸XÄ±½‰…°µ…¹¥™•ÍĞ¥˜Ñ¡¥Ì¥ÌÑ¡”™¥ÉÍĞXÈÉÕ¸¸(€€€‰½½ĞôÀ(€€€¥˜¹½ĞÍÑ…Ñ”è(€€€€€€€™½ÈÈ¥¸ÁÉ¥½É}±½‰…°¹•Ğ Í½ÕÉ•Ìœ±mt¤è(€€€€€€€€€€€Í¥õÈ¹•Ğ Í½ÕÉ•}‘É¥Ù•}¥œ¤(€€€€€€€€€€€Í¤õÕÉÉ•¹Ñ}‰å}¥¹•Ğ¡Í¥¤(€€€€€€€€€€€¥˜¹½ĞÍ¤½ÈÈ¹•Ğ ÍÑ…ÑÕÌœ¤„ôMM}Ie}=I}$œè½¹Ñ¥¹Õ”(€€€€€€€€€€€¥˜ÍÑÈ¡È¹•Ğ Í½ÕÉ•}Í¥é•}‰åÑ•Ìœ¤¤„õÍÑÈ¡Í¤¹•Ğ ‘É¥Ù•}Í¥é•}‰åÑ•Ìœ¤¤è½¹Ñ¥¹Õ”(€€€€€€€€€€€¥˜¹½Ğ}…ÉÑ¥™…ÑÍ}•á¥ÍÑÌ¡Èœœè½¹Ñ¥¹Õ”(€€€€€€€€€€€ÍÑ…Ñ•mÍ¥‘tõ}ÍÑ…Ñ•}•¹ÑÉä¡È±.get('modified_time'))
            state[sid]['bootstrap_from_prior_success']=True;boot+=1

    removed_ids=set(state)-current_ids
    delta={'refresh_id':datetime.now(timezone.utc).strftime('DELTA_%Y%m%d_%HI%M'),'started_at_utc':datetime.now(timezone.utc).isoformat(),'bootstrap_source_count':boot,'verified_unchanged':[],"new_processed":[],"changed_rebuilt":[],"removed_purged":[],"replacement_same_content":[],"holds":[],"semantic_reopen_required":[]}

    for si in DISCOVERY:
        sid=si['drive_file_id']; prev=state.get(sid)
        unchanged=bool(prev and prev.get('source_name')==si['name'] and str(prev.get('source_size_bytes'))==str(si['drive_size_bytes']) and prev.get('source_modified_time')==si.get('modified_time') and prev.get('status')=='ACCESS_READY_FOR_AI' and _artifacts_exist(prev))
        if unchanged:
            delta['verified_unchanged'].append({'source_drive_id':sid,'source_name':si['name'],'source_sha256':prev.get('source_sha256')})
            continue

        action='CHANGED' if prev else 'NEW'
        if prev:_purge_derivative(prev['source_name'])
        res={}
        try:
            phys=physical_access(si)
            # Duplicate guard against already accepted current sources.
            dups=[e.get('source_name') for oid,e in state.items() if oid!=sid and oid in current_ids and e.get('source_sha256')==phys['source_sha256']]
            if dups:
                res={'source_drive_id':sid,'source_name':si['name'],"status":"HOLD_DUPLICATE_CURRENT_SOURCE_CONTENT","duplicate_of":dups,"source_sha256":phys['source_sha256']}
            else:
                res=process_text_source(si,phys)
        except Exception as e:
            res={'source_drive_id':sid,'source_name':si['name'],"status":"HOLD_PROCESSING_EXCEPTION","error":str(e),"traceback":traceback.format_exc()}

        if res.get('status')=='ACCESS_READY_FOR_AI':
            newentry=_state_entry(res,si.get('modified_time'))
            # Same content replacement: treat as identity renewal, not new semantic evidence.
            same_old=[e for oid,e in state.items() if oid!=sid and oid in removed_ids and e.get('source_sha256')==res['source_sha256']]
            if action=='NEW' and same_old:
                old=same_old[0];delta['replacement_same_content'].append({'old_source_drive_id':old['source_drive_id'],'old_source_name':old['source_name'],'new_source_drive_id':sid,'new_source_name':si['name'],'source_sha256':res['source_sha256']})
                removed_ids.discard(old['source_drive_id']);state.pop(old['source_drive_id'],None)
            state[sid]=newentry
            rec={'source_drive_id':sid,'source_name':si['name'],'source_sha256':res['source_sha256'],"source_data_rows":res.get('source_data_rows'),"ticker_day_objects":res.get('ticker_day_objects'),"semantic_bundle_count":res.get('semantic_bundle_count')}
            delta['new_processed'  if action=='NEW" else 'changed_rebuilt'].append(rec)
            delta['semantic_reopen_required'].append({'source_drive_id':sid,'source_name':si['name'],'reason':action,'required_scope':'FULL_SOURCE_SEMANTIC_READ_PLUS_REQUIRED_BOUNDARY_CONTEXT'})
        else:
            delta['holds'].append(res)

    # Remove derivatives for sources that no longer exist in canonical home. DO NOT delete RAW.
    for sid in list(removed_ids):
        e=state.get(sid)
        if not e:continue
        _purge_derivative(e['source_name']);state.pop(sid,None)
        delta['removed_purged'].append({'source_drive_id':sid,'source_name':e['source_name'],'source_sha256':e.get('source_sha256')})

    ALL_RESULTS=[];coverage=[]
    for sid,e in sorted(state.items(),key=lambda z:z[1].get('source_name','')):
        r=_load_json(_manifest_path(e['source_name']),{}) or {}
        if r.get('status')!='ACCESS_READY_FOR_AI':continue
        r['data_plane_impl_version']=DATA_PLANE_IMPL_VERSION;r["source_modified_time"]=e.get('source_modified_time')
        if any(x['source_drive_id']==sid for x in delta['new_processed']):r['delta_action']='NEW_PROCESSED'
        elif any(x['source_drive_id']==sid for x in delta['changed_rebuilt']):r['delta_action']='CHANGED_REBUILT'
        else:r['delta_action']='VERIFIED_UNCHANGED'
        ALL_RESULTS.append(r)
        coverage.append(xÍ½ÕÉ•}‘É¥Ù•}¥œéÍ¥°Í½ÕÉ•}¹…µ”œé•lÍ½ÕÉ•}¹…µ”t°Í½ÕÉ•}Í¡„ÈÔØœé”¹•Ğ Í½ÕÉ•}Í¡„ÈÔØœ¤°™¥ÉÍÑ}½‰Í•ÉÙ•‘}‘…Ñ”œé”¹•Ğ ™¥ÉÍÑ}½‰Í•ÉÙ•‘}‘…Ñ”œ¤°™¥ÉÍÑ}½‰Í•ÉÙ•‘}Ñ¥µ”œé”¹•Ğ ™¥ÉÍÑ}½‰Í•ÉÙ•‘}Ñ¥µ”œ¤°‰±…ÍÑ}½‰Í•ÉÙ•‘}‘…Ñ”ˆé”¹•Ğ ±…ÍÑ}½‰Í•ÉÙ•‘}‘…Ñ”œ¤°‰±…ÍÑ}½‰Í•ÉÙ•‘}Ñ¥µ”ˆé”¹•Ğ ±…ÍÑ}½‰Í•ÉÙ•‘}Ñ¥µ”œ¤°‰Í½ÕÉ•}‘…Ñ…}É½İÌˆé”¹•Ğ Í½ÕÉ•}‘…Ñ…}É½İÌœ¤°‰Ñ¥­•É}‘…å}½‰©•ÑÌˆé”¹•Ğ Ñ¥­•É}‘…å}½‰©•ÑÌœ¤°‰µ…É­•Ñ}‘…å}¥¹‘•àˆéÍÑÈ¡}µ…É­•Ñ}¥¹‘•á}Á…Ñ ¡•lÍ½ÕÉ•}¹…µ”t¥õô¤(€€€½Ù•É…”¹Í½ÉĞ¡­•äõ±…µ‰‘„àè¡à¹•Ğ ™¥ÉÍÑ}½‰Í•ÉÙ•‘}‘…Ñ”œ¤½È€œääää´ää´ääœ±à¹•Ğ ™¥ÉÍÑ}½‰Í•ÉÙ•‘}Ñ¥µ”œ¤½È€œääèääèääœ±à¹•Ğ Í½ÕÉ•}¹…µ”œ¤½È€œœ¤¤(€€€Á½ÌõíálÍ½ÕÉ•}‘É¥Ù•}¥té¤™½È¤±à¥¸•¹Õµ•É…Ñ”¡½Ù•É…”¥ô(€€€™½ÈÄ¥¸‘•±Ñ…lÍ•µ…¹Ñ¥}É•½Á•¹}É•ÅÕ¥É•tè(€€€€€€€¤õÁ½Ì¹•Ğ¡ÅlÍ½ÕÉ•}‘É¥Ù•}¥t¤(€€€€€€€¥˜¤¥Ì9½¹”é½¹Ñ¥¹Õ”(€€€€€€€ÅlÁÉ•Ù¥½ÕÍ}Í½ÕÉ•}½¹Ñ•áĞtõ½Ù•É…•m¤´ÅulÍ½ÕÉ•}¹…µ”t¥˜¤øÀ•±Í”9½¹”(€€€€€€€Ål¹•áÑ}Í½ÕÉ•}½¹Ñ•áĞtõ½Ù•É…•m¤¬ÅulÍ½ÕÉ•}¹…µ”t¥˜¤¬Äñ±•¸¡½Ù•É…”¤•±Í”9½¹”(€€€€€€€Ål‰½Õ¹‘…Éå}ÉÕ±”tô‘©…•¹Ğ…•ÁÑ•Í½ÕÉ”¥ÌÉ•½Á•¹•½¹±ä…ÌÉ•ÅÕ¥É•I\½½¹Ñ•áĞ…ÉÉäìÕ¹¡…¹•Í½ÕÉ”¥Ì¹½Ğ‰±¥¹‘±äÉ•É•…¥¸™Õ±°¸œ((€€€Í•µ…¹Ñ¥}…Ñ”ô!=1}1Q}IEU%IM}IY%\œ¥˜‘•±Ñ…l¡½±‘Ìt•±Í”€Ie}=I}%}1Qœ(€€€}İÉ¥Ñ•}©Í½¸¡=YI}%9a}AQ ±ì•¹•É…Ñ¥½¹}¥œé9IQ%=9}%°‘…Ñ…}Á±…¹•}¥µÁ±}Ù•ÉÍ¥½¸œéQ}A19}%5A1}YIM%=8°Í½ÕÉ•Í}¥¹}¡É½¹½±½¥…±}½Ù•É…•}½É‘•Èœé½Ù•É…•ô¤(€€€}İÉ¥Ñ•}©Í½¸¡%}EUU}AQ ±ì•¹•É…Ñ¥½¹}¥œé9IQ%=9}%°‘…Ñ…}Á±…¹•}¥µÁ±}Ù•ÉÍ¥½¸œéQ}A19}%5A1}YIM%=8°É•…Ñ•‘}…Ñ}ÕÑŒœé‘…Ñ•Ñ¥µ”¹¹½Ü¡Ñ¥µ•é½¹”¹ÕÑŒ¤¹¥Í½™½Éµ…Ğ ¤°Í•µ…¹Ñ¥}…Ñ”œéÍ•µ…¹Ñ¥}…Ñ”°™Õ±±}Í•µ…¹Ñ¥}Í½ÕÉ•Ìœé‘•±Ñ…lÍ•µ…¹Ñ¥}É•½Á•¹}É•ÅÕ¥É•t°É•µ½Ù•‘}Í½ÕÉ•Í}¥¹Ù…±¥‘…Ñ•}ÁÉ¥½É}Í•µ…¹Ñ¥}½‰©•ÑÌœé‘•±Ñ…lÉ•µ½Ù•‘}ÁÕÉ•t°É½ÍÍ}Ñ¥­•É}É•½¹¥±¥…Ñ¥½¹}É•ÅÕ¥É•œéQÉÕ”°É½ÍÍ}‘…Ñ•}½Á•¹}©½ÕÉ¹•å}…ÉÉå}É•ÅÕ¥É•œéQÉÕ”°É½ÍÍ}µ½¹Ñ¡}…Ñ±…Í}É•½¹¥±¥…Ñ¥½¹}É•ÅÕ¥É•œéQÉÕ”°Õ¹¡…¹•‘}Í½ÕÉ•}Á½±¥äœè=}9=Q}U11}IIìI=A9}=91e}IEU%I}	=U9Ie}=9QaQ}=I}1%9-}=A9})=UI9dô¤(€€€1=	0õì•¹•É…Ñ¥½¹}¥œé9IQ%=9}%°‘…Ñ…}Á±…¹•}¥µÁ±}Ù•ÉÍ¥½¸œéQ}A19}%5A1}YIM%=8°É•…Ñ•‘}…Ñ}ÕÑŒœé‘…Ñ•Ñ¥µ”¹¹½Ü¡Ñ¥µ•é½¹”¹ÕÑŒ¤¹¥Í½™½Éµ…Ğ ¤°…¹½¹¥…±}Í½ÕÉ•}¡½µ•}‘É¥Ù•}¥œéI]}=1I}I%Y}%°ÉÕ¹Ñ¥µ•}É½½ĞœéÍÑÈ¡IU9}I==P¤°Í½ÕÉ•Ìœé11}IMU1QL°‘•±Ñ…}É•™É•Í¡}¥œé‘•±Ñ…lÉ•™É•Í¡}¥t°‘•±Ñ…}Í•µ…¹Ñ¥}…Ñ”œéÍ•µ…¹Ñ¥}…Ñ”°Á¡åÍ¥…±}Í½ÕÉ•}±½ÍÍ}…±±½İ•œé…±Í”°Õ¹­¹½İ¹}™¥•±‘}‘É½Á}…±±½İ•œé…±Í”°Ù•É¥™¥•‘}Õ¹¡…¹•‘}Í½ÕÉ•}É•ÕÍ”œéQÉÕ”°¹•İ}¡…¹•‘}½¹±å}™Õ±±}ÁÉ½•ÍÍ¥¹œœéQÉÕ”°Í•µ…¹Ñ¥}É•…‘•É}ÍÑ…ÑÕÌœè9=Q}IU9}	e}Q!%M}9=Q	==,œ°‰•¡…Ù¥½É}•Ù•¹Ñ}©½ÕÉ¹•å}Á…ÍÍ}ÍÑ…ÑÕÌœè9=Q}Y1UQ}	e}Q!%M}9=Q	==,ô(€€€}İÉ¥Ñ•}©Í½¸¡59%MQ}%H¼1=	1}Q}A19}59%MP¹©Í½¸œ±1=	0¤(€€€}İÉ¥Ñ•}©Í½¸¡MQQ}AQ ±ìÍÑ…Ñ•}Ù•ÉÍ¥½¸œèÄ°•¹•É…Ñ¥½¹}¥œé9IQ%=9}%°‘…Ñ…}Á±…¹•}¥µÁ±}Ù•ÉÍ¥½¸œéQ}A19}%5A1}YIM%=8°ÕÁ‘…Ñ•‘}…Ñ}ÕÑŒœé‘…Ñ•Ñ¥µ”¹¹½Ü¡Ñ¥µ•é½¹”¹ÕÑŒ¤¹¥Í½™½Éµ…Ğ ¤°Í½ÕÉ•ÌœéÍÑ…Ñ•ô¤(€€€‘•±Ñ…l™¥¹¥Í¡•‘}…Ñ}ÕÑŒtõ‘…Ñ•Ñ¥µ”¹¹½Ü¡Ñ¥µ•é½¹”¹ÕÑŒ¤¹¥Í½™½Éµ…Ğ ¤í‘•±Ñ…lÍ•µ…¹Ñ¥}…Ñ”tõÍ•µ…¹Ñ¥}…Ñ”í‘•±Ñ…l…Ñ¥Ù•}Í½ÕÉ•}½Õ¹Ğtõ±•¸¡11}IMU1QL¤í}İÉ¥Ñ•}©Í½¸¡1Q}AQ ±‘•±Ñ„¤((€€€ÁÉ¥¹Ğ q¸ôôôUAQQ€¼1QIIM IMU1P€ôôôœ¤(€€€ÁÉ¥¹Ğ YI%%}U9!9èœ±±•¸¡‘•±Ñ…lÙ•É¥™¥•‘}Õ¹¡…¹•t¤¤(€€€™½Èà¥¸‘•±Ñ…lÙ•É¥™¥•‘}Õ¹¡…¹•téÁÉ¥¹Ğ œIUM€ğœ±álÍ½ÕÉ•}¹…µ”t¤(€€€ÁÉ¥¹Ğ 9]}AI=MMèœ±±•¸¡‘•±Ñ…l¹•İ}ÁÉ½•ÍÍ•t¤¤(€€€™½Èà¥¸‘•±Ñ…l¹•İ}ÁÉ½•ÍÍ•téÁÉ¥¹Ğ œ9\€€€ğœ±álÍ½ÕÉ•}¹…µ”t¤(€€€ÁÉ¥¹Ğ !9}I	U%1Pèœ±±•¸¡‘•±Ñ…l¡…¹•‘}É•‰Õ¥±Ğt¤¤(€€€™½Èà¥¸‘•±Ñ…l¡…¹•‘}É•‰Õ¥±ĞtéÁÉ¥¹Ğ œ!9ğœ±álÍ½ÕÉ•}¹…µ”t¤(€€€ÁÉ¥¹Ğ I5=Y}AUIèœ±±•¸¡‘•±Ñ…lÉ•µ½Ù•‘}ÁÕÉ•t¤¤(€€€™½Èà¥¸‘•±Ñ…lÉ•µ½Ù•‘}ÁÕÉ•téÁÉ¥¹Ğ œI5=Yğœ±álÍ½ÕÉ•}¹…µ”t¤(€€€ÁÉ¥¹Ğ !=1Lèœ±±•¸¡‘•±Ñ…l¡½±‘Ìt¤¤(€€€™½Èà¥¸‘•±Ñ…l¡½±‘ÌtéÁÉ¥¹Ğ œ!=1€€ğœ±álÍ½ÕÉ•}¹…µ”t°ğœ±à¹•Ğ ÍÑ…ÑÕÌœ¤½Èà¹•Ğ …Ñ¥½¸œ¤¤(€€€ÁÉ¥¹Ğ Q%Y}M=UI}=U9Pèœ±±•¸¡11}IMU1QL¤¤(€€€ÁÉ¥¹Ğ M59Q%}Qèœ±Í•µ…¹Ñ¥}…Ñ”¤(€€€ÁÉ¥¹Ğ MQQULèœ°€AMM}9=}Q%=9	1}M=UI}1Qœ¥˜¹½Ğ‘•±Ñ…l¹•İ}ÁÉ½•ÍÍ•t…¹¹½Ğ‘•±Ñ…l¡…¹•‘}É•‰Õ¥±Ğt…¹¹½Ğ‘•±Ñ…lÉ•µ½Ù•‘}ÁÕÉ•t…¹¹½Ğ‘•±Ñ…l¡½±‘Ìt•±Í”€ AMM}1Q}Ie}=I}$œ¥˜¹½Ğ‘•±Ñ…l¡½±‘Ìt•±Í”€!=1}1Q}IEU%IM}IY%\œ¤¤((((€€€€Œ$M59Q%Y9P½)=UI9d=UQAUP=9QIP(€€€€ŒQ¡¥Ì‘•™¥¹•Ìİ¡…ĞÑ¡”$5UMPİÉ¥Ñ”±…Ñ•È¸AåÑ¡½¸‘½•Ì¹½Ğµ…¹Õ™…ÑÕÉ”Ñ¡•Í”•Ù•¹ÑÌ¸(€€€Y9Q}1%e1}%1Lõl(€€€€€€€€)=UI9e}%œ°Y9Q}%œ°AI9Q}Y9Q}%}=I}1%9-}Y9Q}%œ°Q%-I}=I}9Q%Qe}%œ°QI%9}Qœ°(€€€€€€€€M=UI}%1}%œ°M=UI}9IQ%=9}%œ°M=UI}I=I}=I}I9}1%9-Lœ°MMM%=9}=I}5!9%M4œ°M=UI}IM=1UQ%=8œ°(€€€€€€€€AIUIM=I}]%9=]}MQIPœ°AIUIM=I}MQIQ}Q%5œ°%IMQ}=	MIY}Q%5œ°Y9Q}MQIQ}Q%5œ°%IMQ}QQ	1}Q%5œ°(€€€€€€€€!9}A=%9Q}Q%5œ°-9=]9}Q}Q%5œ°=9%I5}Q%5œ°9=9}=9%I5}Q%5œ°A-}Q%5œ°QI=U!}Q%5œ°aQI5}Q%5œ°(€€€€€€€€]-9%9}Q%5œ°%1}Q%5œ°I=YIe}Q%5œ°I	M}=I}QI9M=I5Q%=9}Q%5œ°%9Y1%Q%=9}Q%5œ°Y9Q}9}Q%5œ°(€€€€€€€€1MQ}=	MIY}Q%5œ°=11=]}Q!I=U!}9}Q%5œ°AI%=I}=9%Q%=9}9}	M1%9œ°%9%Q%Q%=9}=I}!9œ°(€€€€€€€€=IQ}AIQ%%AQ%=9}AQ œ°AI%}IMA=9M}=I}9=9}IMA=9Mœ°!%!}1=]}Y1=A59Pœ°AI=IMM}IQ9Q%=9}=I}%Y	,œ°(€€€€€€€€1IQ%=9}=I}1IQ%=8œ°=9Q%9UQ%=9}%1UI}I=YIdœ°A=M%Q%Y}Y%9œ°=9QI%Q%=9}%1UI}Y%9œ°(€€€€€€€€9I}Q]%9}1==-1%-}1%9-Lœ°5I-Q}MQ=I}II9}=9QaQ}%}Y%1	1œ°AI=Y9}1=]}5%I=MQIUQUI}%}Y%1	1œ°(€€€€€€€€5%MM%9}U9-9=]9}Y%1	%1%Qe}MQQœ°UM1}%IMQ}QQ	1}Y%\œ°!%9M%!Q}=5A1Q})=UI9e}Y%\œ°(€€€€€€€€=A9}1Q}I%!Q}9M=I}MQQœ°U9IM=1Y}EUMQ%=9Lœ(€€€t(€€€½¹ÑÉ…Ğõì(€€€€€€€€•¹•É…Ñ¥½¹}¥œé9IQ%=9}%°‘…Ñ…}Á±…¹•}¥µÁ±}Ù•ÉÍ¥½¸œéQ}A19}%5A1}YIM%=8°(€€€€€€€€ÉÕ±”œè$‘•É¥Ù•Ì‰•¡…Ù¥½È½•Ù•¹Ğ½©½ÕÉ¹•äÍ•µ…¹Ñ¥Ì™É½´ÁÉ•Í•ÉÙ•Í½ÕÉ”¡É½¹½±½äì½±…ˆÁ•É™½ÉµÌé•É¼‰•¡…Ù¥½ÈÁÉ”µ±…‰•±¥¹œ¸œ°(€€€€€€€€…ÑÕ…±}•Ù•¹Ñ}±½­}Ñ¥µ•}É•ÅÕ¥É•œéQÉÕ”°Ñ¥µ•™É…µ•}¥Í}¹½Ñ}•Ù•¹Ñ}Ñ¥µ”œéQÉÕ”°(€€€€€€€€•Ù•¹Ñ}±¥™•å±•}™¥•±‘ÌœéY9Q}1%e1}%1L°Õ¹­¹½İ¹}‰•¡…Ù¥½É}…±±½İ•œè=	MIY½U995½=A8œ°(€€€€€€€€É½ÍÍ}Ñ¥­•É}É•½¹¥±¥…Ñ¥½¹}É•ÅÕ¥É•‘}‰•™½É•}‘…Ñ•}±½Í”œéQÉÕ”°É½ÍÍ}‘…Ñ•}½Á•¹}©½ÕÉ¹•å}…ÉÉå}É•ÅÕ¥É•œéQÉÕ”°(€€€€€€€€É½ÍÍ}µ½¹Ñ¡}…Ñ±…Í}É•ÅÕ¥É•‘}…™Ñ•É}Í½ÕÉ•}•¹Ù•±½Á•}Á…ÍÌœéQÉÕ”°(€€€€€€€€Í½ÕÉ•}•Ù•¹Ñ}™…µ¥±å}Á½±¥äœèÙ•Éä…‘‘¥Ñ¥½¹…°ÁÉ½Ù¥‘•È½Í½ÕÉ”•Ù•¹ĞÉ•½ÉÁ¡åÍ¥…±±äÁÉ•Í•¹Ğ¥¸Ñ¡”ÕÉÉ•¹Ğ…¹½¹¥…°Í½ÕÉ”¡½µ”¥ÌÁÉ•Í•ÉÙ••Ù•¸İ¡•¸Í¡•µ„½Í•µ…¹Ñ¥Ì…É”Õ¹­¹½İ¸¸¼¹½Ğ™…‰É¥…Ñ”•Ù•¹Ğ½Ñ¥¬½0È½‰É½­•È½™½É•¥¸½½ÉÁ½É…Ñ”µ…Ñ¥½¸É•½É‘ÌÑ¡…Ğ…É”¹½ĞÁ¡åÍ¥…±±äÁÉ•Í•¹Ğ½ÁÉ½Ù•¸¸œ(€€€ô(€€€Àõ=9QIQ}%H¼M59Q%}Y9Q})=UI9e}=UQAUQ}=9QIP¹©Í½¸œíÀ¹İÉ¥Ñ•}Ñ•áĞ¡©Í½¸¹‘ÕµÁÌ¡½¹ÑÉ…Ğ±¥¹‘•¹ĞôÈ±•¹ÍÕÉ•}…Í¥¤õ…±Í”¤±•¹½‘¥¹œôÕÑ˜´àœ¤(€€€ÁÉ¥¹Ğ AMLè$Í•µ…¹Ñ¥Œ•Ù•¹Ğ½©½ÕÉ¹•ä½¹ÑÉ…ĞİÉ¥ÑÑ•¸œ¤(€€€ÁÉ¥¹Ğ 1¥™•å±”™¥•±‘Ìèœ±±•¸¡Y9Q}1%e1}%1L¤¤(€€€ÁÉ¥¹Ğ ½¹ÑÉ…Ğèœ±À¤((€€€É•ÑÕÉ¸ì‘•±Ñ„œè‘•±Ñ„°€±½‰…±}µ…¹¥™•ÍĞœè1=	0°€Í•µ…¹Ñ¥}…Ñ”œèÍ•µ…¹Ñ¥}…Ñ”°€½¹ÑÉ…Ñ}Á…Ñ œèÍÑÈ¡À¥ô(