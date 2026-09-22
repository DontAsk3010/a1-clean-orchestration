param([Parameter(Mandatory=$true)][string]$OutputDir)
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
$FolderId='1X_LxFsU6c_YKUhJO5Vb5ZM8N3lMsmE-D'
$RegistryId='1hI1HAksSGktmjL0sqB1SUhGDaS7NQILHdBoSnE2vR7Q'
$Scope='https://www.googleapis.com/auth/drive.readonly'

function Prop($o,[string]$n){
  if($null -eq $o){return $null}
  $p=$o.PSObject.Properties[$n]
  if($null -eq $p){return $null}
  return $p.Value
}
function B64Url([byte[]]$b){[Convert]::ToBase64String($b).TrimEnd('=').Replace('+','-').Replace('/','_')}
function Token([string]$path){
  $c=Get-Content -LiteralPath $path -Raw -Encoding UTF8|ConvertFrom-Json
  $t=[string](Prop $c 'type')
  $uri=[string](Prop $c 'token_uri'); if([string]::IsNullOrWhiteSpace($uri)){$uri='https://oauth2.googleapis.com/token'}
  if($t -eq 'authorized_user'){
    $body=@{client_id=[string](Prop $c 'client_id');client_secret=[string](Prop $c 'client_secret');refresh_token=[string](Prop $c 'refresh_token');grant_type='refresh_token'}
    return [string](Invoke-RestMethod -Method Post -Uri $uri -Body $body -ContentType 'application/x-www-form-urlencoded').access_token
  }
  if($t -eq 'service_account'){
    $openssl=$null;$cmd=Get-Command openssl.exe -ErrorAction SilentlyContinue
    if($null-ne $cmd){$openssl=$cmd.Source}elseif(Test-Path 'C:\Program Files\Git\usr\bin\openssl.exe'){$openssl='C:\Program Files\Git\usr\bin\openssl.exe'}
    if([string]::IsNullOrWhiteSpace($openssl)){throw 'openssl.exe not found for service-account auth'}
    $now=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds();$enc=New-Object Text.UTF8Encoding($false)
    $h=B64Url($enc.GetBytes('{"alg":"RS256","typ":"JWT"}'))
    $claims=[ordered]@{iss=[string](Prop $c 'client_email');scope=$Scope;aud=$uri;iat=$now;exp=$now+3600}|ConvertTo-Json -Compress
    $p=B64Url($enc.GetBytes($claims));$u="$h.$p";$n=[guid]::NewGuid().ToString('N')
    $in=Join-Path $env:RUNNER_TEMP "a1-$n.in";$key=Join-Path $env:RUNNER_TEMP "a1-$n.pem";$sig=Join-Path $env:RUNNER_TEMP "a1-$n.sig"
    try{
      [IO.File]::WriteAllText($in,$u,[Text.Encoding]::ASCII);[IO.File]::WriteAllText($key,[string](Prop $c 'private_key'),$enc)
      & $openssl dgst -sha256 -sign $key -out $sig $in|Out-Null
      if($LASTEXITCODE-ne 0){throw 'service-account JWT signing failed'}
      $a="$u.$(B64Url([IO.File]::ReadAllBytes($sig)))"
      return [string](Invoke-RestMethod -Method Post -Uri $uri -Body @{grant_type='urn:ietf:params:oauth:grant-type:jwt-bearer';assertion=$a} -ContentType 'application/x-www-form-urlencoded').access_token
    }finally{Remove-Item $in,$key,$sig -Force -ErrorAction SilentlyContinue}
  }
  throw "unsupported credential type: $t"
}
function DateKey([string]$s){"$($s.Substring(0,4))-$($s.Substring(4,2))-$($s.Substring(6,2))"}
function CountVal($v){
  if($null-eq $v){return @($null,$null)};$s=([string]$v).Trim()
  if($s-match '^\d+$'){return @([int]$s,$null)}
  if($s-match '^(\d+)\s*/\s*(\d+)$'){return @([int]$Matches[1],[int]$Matches[2])}
  return @($null,$null)
}
function Ticker($v){
  if($null-eq $v){return $null};$x=Prop $v 'ticker';if(-not[string]::IsNullOrWhiteSpace([string]$x)){return [string]$x}
  return ([string]$v).Split('|')[0].Trim()
}
function Children([string]$tok){
  $h=@{Authorization="Bearer $tok"};$out=@();$page=$null
  do{
    $q="'$FolderId' in parents and trashed=false"
    $url='https://www.googleapis.com/drive/v3/files?q='+[uri]::EscapeDataString($q)+'&pageSize=1000&orderBy=name&fields='+[uri]::EscapeDataString('nextPageToken,files(id,name,modifiedTime)')
    if($page){$url+='&pageToken='+[uri]::EscapeDataString([string]$page)}
    $r=Invoke-RestMethod -Uri $url -Headers $h;if($r.files){$out+=@($r.files)};$page=Prop $r 'nextPageToken'
  }while($page)
  return @($out)
}
function JsonFile([string]$tok,[string]$id){Invoke-RestMethod -Uri "https://www.googleapis.com/drive/v3/files/$id?alt=media" -Headers @{Authorization="Bearer $tok"}}
function Registry([string]$tok){
  $mime=[uri]::EscapeDataString('text/plain');$txt=(Invoke-WebRequest -UseBasicParsing -Uri "https://www.googleapis.com/drive/v3/files/$RegistryId/export?mimeType=$mime" -Headers @{Authorization="Bearer $tok"}).Content
  $states=@{};$b=@{}
  function Flush($states,$b){
    if(-not $b.ContainsKey('DATE')){return};$d=[string]$b.DATE;if($d-notmatch '^\d{4}-\d{2}-\d{2}$'){return}
    if(-not $states.ContainsKey($d)){$states[$d]=@{}};foreach($k in $b.Keys){if(-not[string]::IsNullOrWhiteSpace([string]$b[$k])){$states[$d][$k]=$b[$k]}}
  }
  foreach($raw in ($txt -split '\r?\n')){
    $line=$raw.Trim().TrimStart([char]0xFEFF)
    if($line.StartsWith('MACHINE-1 ') -or $line-eq 'CURRENT MACHINE-1 REGISTER'){Flush $states $b;$b=@{};continue}
    if($line-match '^([A-Z][A-Z0-9_\-]*)=(.*)$'){$b[$Matches[1]]=$Matches[2].Trim()}
  }
  Flush $states $b;return $states
}
function Row($p,$m,[string]$kind,[int]$pass){
  $scope=Prop $p 'date_scope';$cons=Prop $p 'consistency_test';$ev=Prop $p 'evidence_access';if($null-eq $ev){$ev=Prop $p 'evidence'}
  $cv=Prop $p 'completed_ticker_context_paths';if($null-eq $cv -and $scope){$cv=Prop $scope 'completed_ticker_context_paths'};$c=CountVal $cv
  $tv=Prop $p 'total_ticker_context_paths';if($null-eq $tv -and $scope){$tv=Prop $scope 'total_ticker_context_paths'};$total=$c[1];if($tv -and ([string]$tv)-match '^\d+$'){$total=[int]$tv}
  $last=Prop $p 'last_verified_ticker';if(-not $last -and $scope){$done=@(Prop $scope 'completed');if($done.Count){$last=$done[-1]}}
  $next=Prop $p 'next_exact_resume';if($null-eq $next){$next=Prop $p 'next_exact_resume_point'}
  $cp=Prop $p 'checkpoint';if(-not $cp -and $cons){$cp=Prop $cons 'atomic_checkpoint_state'};if(-not $cp){$cp=Prop $p 'checkpoint_id'}
  $state=Prop $p 'state';if(-not $state){$state=Prop $p 'status'};if(-not $state){$state=Prop $p 'date_status'}
  $rb=Prop $p 'atomic_artifact_readback';if(-not $rb){$rb=Prop $p 'readback_status'};if(-not $rb -and $kind-eq 'CURRENT'){$rb='CURRENT_DURABLE'}
  [pscustomobject]@{kind=$kind;pass=$pass;worker=Prop $p 'worker_id';state=$state;datepass=Prop $p 'date_local_pass';checkpoint=$cp;completed=$c[0];total=$total;last=$last;next=Ticker $next;nextexact=$next;rows=Prop $p 'actual_source_rows_read';readback=$rb;pull=Prop $ev 'mode';run=Prop $ev 'github_run_id';artifact=Prop $ev 'github_artifact_id';modified=Prop $m 'modifiedTime';file=Prop $m 'name'}
}
function RegRow($r){
  $cv=if($r.ContainsKey('COMPLETED_TICKER_CONTEXT_PATHS')){$r.COMPLETED_TICKER_CONTEXT_PATHS}else{$null};$c=CountVal $cv
  $tot=$c[1];if($r.ContainsKey('TOTAL_TICKER_CONTEXT_PATHS') -and ([string]$r.TOTAL_TICKER_CONTEXT_PATHS)-match '^\d+$'){$tot=[int]$r.TOTAL_TICKER_CONTEXT_PATHS}
  [pscustomobject]@{kind='REGISTRY';pass=-1;worker=if($r.ContainsKey('WORKER_ID')){$r.WORKER_ID}else{$null};state=if($r.ContainsKey('STATE')){$r.STATE}elseif($r.ContainsKey('DATE_STATUS')){$r.DATE_STATUS}else{$null};datepass=if($r.ContainsKey('DATE_LOCAL_PASS')){$r.DATE_LOCAL_PASS}else{$null};checkpoint=if($r.ContainsKey('CHECKPOINT')){$r.CHECKPOINT}elseif($r.ContainsKey('CHECKPOINT_POINTER')){$r.CHECKPOINT_POINTER}else{$null};completed=$c[0];total=$tot;last=if($r.ContainsKey('LAST_VERIFIED_TICKER')){$r.LAST_VERIFIED_TICKER}else{$null};next=if($r.ContainsKey('NEXT_EXACT_RESUME')){Ticker $r.NEXT_EXACT_RESUME}else{$null};nextexact=if($r.ContainsKey('NEXT_EXACT_RESUME')){$r.NEXT_EXACT_RESUME}else{$null};rows=if($r.ContainsKey('ACTUAL_SOURCE_ROWS_READ')){$r.ACTUAL_SOURCE_ROWS_READ}else{$null};readback=if($r.ContainsKey('READBACK_STATUS')){$r.READBACK_STATUS}else{$null};pull=$null;run=$null;artifact=$null;modified=$null;file=$null;handoff=if($r.ContainsKey('HANDOFF_TICKET')){$r.HANDOFF_TICKET}else{$null};assignment=if($r.ContainsKey('ASSIGNMENT')){$r.ASSIGNMENT}else{$null}}
}

New-Item -ItemType Directory -Force -Path $OutputDir|Out-Null
if(-not(Test-Path -LiteralPath $env:A1_DRIVE_READER_CREDENTIALS -PathType Leaf)){throw 'reader credential file missing'}
$tok=Token $env:A1_DRIVE_READER_CREDENTIALS
$items=Children $tok;$selected=@();$ab=@{}
foreach($m in $items){
  $n=[string](Prop $m 'name')
  if($n-match '^DES2024_(\d{8})__CHECKPOINT_CURRENT\.json$'){$selected+=$m;continue}
  if($n-match '^DES2024_(\d{8})__CHECKPOINT_ATOMIC_PASS(\d+)(?:_.*)?\.json$'){
    $d=DateKey $Matches[1];$p=[int]$Matches[2];if(-not$ab.ContainsKey($d) -or $p-gt$ab[$d].p){$ab[$d]=[pscustomobject]@{p=$p;m=$m}}
  }
}
foreach($v in $ab.Values){$selected+=$v.m}
$by=@{};$holds=@()
foreach($m in $selected){
  $n=[string](Prop $m 'name');$kind=$null;$pass=-1;$d=$null
  if($n-match '^DES2024_(\d{8})__CHECKPOINT_CURRENT\.json$'){$d=DateKey $Matches[1];$kind='CURRENT'}
  elseif($n-match '^DES2024_(\d{8})__CHECKPOINT_ATOMIC_PASS(\d+)(?:_.*)?\.json$'){$d=DateKey $Matches[1];$kind='ATOMIC';$pass=[int]$Matches[2]}
  if(-not$kind){continue}
  try{$rr=Row (JsonFile $tok ([string](Prop $m 'id'))) $m $kind $pass;if(-not$by.ContainsKey($d)){$by[$d]=@()};$by[$d]+=$rr}catch{$holds+=[pscustomobject]@{file=$n;error=$_.Exception.Message}}
}
$regerr=$null;try{$reg=Registry $tok}catch{$reg=@{};$regerr=$_.Exception.Message}
$dates=New-Object 'Collections.Generic.HashSet[string]';foreach($d in $by.Keys){[void]$dates.Add($d)};foreach($d in $reg.Keys){[void]$dates.Add($d)}
$now=[DateTimeOffset]::UtcNow;$workers=@()
foreach($d in ($dates|Sort-Object)){
  $fr=if($by.ContainsKey($d)){@($by[$d])}else{@()}
  $cur=@($fr|?{$_.kind-eq'CURRENT'}|Sort-Object modified -Descending|Select-Object -First 1);$cur=if($cur.Count){$cur[0]}else{$null}
  $atom=@($fr|?{$_.kind-eq'ATOMIC'}|Sort-Object pass -Descending|Select-Object -First 1);$atom=if($atom.Count){$atom[0]}else{$null}
  $rg=if($reg.ContainsKey($d)){RegRow $reg[$d]}else{$null}
  $cand=@();if($cur){$cand+=$cur};if($atom){$cand+=$atom};if($rg){$cand+=$rg}
  $best=@($cand|?{$null-ne$_.completed}|Sort-Object @{e={[int]$_.completed};Descending=$true},@{e={if($_.kind-eq'REGISTRY'){0}else{1}};Descending=$true}|Select-Object -First 1);$best=if($best.Count){$best[0]}elseif($cur){$cur}elseif($atom){$atom}else{$rg}
  $hb=@($fr|?{$_.modified}|Sort-Object modified -Descending|Select-Object -First 1);$hb=if($hb.Count){$hb[0]}else{$null}
  $age=$null;$health='NO_FILE_HEARTBEAT';if($hb){$age=[math]::Max(0,[int][math]::Floor(($now-[DateTimeOffset]::Parse($hb.modified)).TotalMinutes));$health=if($age-le20){'RECENT_WRITE'}elseif($age-le90){'QUIET_NO_RECENT_WRITE'}else{'STALE_OBSERVATION_ONLY'}}
  $wid='UNKNOWN_FROM_CHECKPOINT';foreach($x in @($rg,$atom,$cur)){if($x -and $x.worker){$wid=[string]$x.worker;break}}
  $pull=if($atom -and $atom.pull){$atom}else{$cur};$rb=if($best){$best.readback}else{$null};if(-not$rb){foreach($x in $cand){if($x.readback){$rb=$x.readback;break}}};if(-not$rb){$rb='UNKNOWN'}
  $comp=if($best){$best.completed}else{$null};$tot=if($best){$best.total}else{$null};$rem=if($null-ne$comp -and $null-ne$tot){[int]$tot-[int]$comp}else{$null};$pct=if($tot){[math]::Round(100.0*[int]$comp/[int]$tot,2)}else{$null}
  $store=if(-not$hb){'NO_DURABLE_CHECKPOINT_FOUND'}elseif(([string]$rb).ToUpper()-eq'PENDING'){'CHECKPOINT_WRITTEN_READBACK_PENDING'}else{'OK'}
  $workers+=[pscustomobject][ordered]@{trading_date=$d;worker_id=$wid;health=$health;heartbeat_age_minutes=$age;checkpoint_source=if($best){$best.kind}else{$null};checkpoint=if($best){$best.checkpoint}else{$null};completed_ticker_context_paths=$comp;total_ticker_context_paths=$tot;remaining_ticker_context_paths=$rem;progress_pct=$pct;last_verified_ticker=if($best){$best.last}else{$null};next_ticker=if($best){$best.next}else{$null};next_exact_resume=if($best){$best.nextexact}else{$null};actual_source_rows_read=if($best){$best.rows}else{$null};pull_status=if($pull -and $pull.pull){'OK'}else{'NOT_EXPOSED_IN_SELECTED_CHECKPOINT'};pull_mode=if($pull){$pull.pull}else{$null};github_run_id=if($pull){$pull.run}else{$null};github_artifact_id=if($pull){$pull.artifact}else{$null};store_status=$store;readback_status=$rb;heartbeat_file=if($hb){$hb.file}else{$null};heartbeat_time_utc=if($hb){$hb.modified}else{$null};official_current=$cur;latest_atomic=$atom}
}
$status=if($holds.Count-eq0 -and -not$regerr){'PASS'}else{'PARTIAL_READ_HOLD'}
$snap=[pscustomobject][ordered]@{schema='A1_MACHINE1_MULTIWORKER_OBSERVABILITY_V1';generated_at_utc=$now.UtcDateTime.ToString('yyyy-MM-ddTHH:mm:ssZ');role='READ_ONLY_OBSERVABILITY_NO_ANALYTICAL_AUTHORITY';monitor_status=$status;worker_count=$workers.Count;workers=$workers;artifact_read_holds=$holds;registry_read_error=$regerr;safety=[pscustomobject]@{raw_write=$false;current_write=$false;registry_write=$false;semantic_interpretation=$false;formula_or_signal_logic=$false}}
$snap|ConvertTo-Json -Depth 30|Set-Content -Encoding UTF8 -LiteralPath (Join-Path $OutputDir 'machine1-monitor-latest.json')
$md=@('# A1 CLEAN — MACHINE 1 LIVE MONITOR','',"Generated: $($snap.generated_at_utc)","Monitor status: $status",'','| Date | Worker | Health | Progress | Last | Next | Pull | Store / Readback | Age |','|---|---|---|---|---|---|---|---|---|')
foreach($w in $workers){$pr="$($w.completed_ticker_context_paths)/$($w.total_ticker_context_paths)";if($null-ne$w.progress_pct){$pr+=" ($($w.progress_pct)%)"};$ag=if($null-ne$w.heartbeat_age_minutes){"$($w.heartbeat_age_minutes) min"}else{'-'};$md+="| $($w.trading_date) | $($w.worker_id) | $($w.health) | $pr | $($w.last_verified_ticker) | $($w.next_ticker) | $($w.pull_status) | $($w.store_status) / $($w.readback_status) | $ag |"}
$md+='';$md+='> Read-only observability only. No RAW/CURRENT/registry/semantic write and no formula/signal logic.'
$md|Set-Content -Encoding UTF8 -LiteralPath (Join-Path $OutputDir 'machine1-monitor-latest.md')
Write-Host "Machine 1 monitor: $status; workers=$($workers.Count)"
