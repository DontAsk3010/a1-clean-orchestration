$ErrorActionPreference='Stop'
Add-Type -AssemblyName Microsoft.VisualBasic
$raw='D:\TRADING SYSTEM\02_CURRENT_HISTORICAL_RAW_DATA_UJI\Raw Des 02-31-2024.csv'
$date='2024-12-02'
$md5='b8d42b35c90d2dff8b18ae4e1734523b'
$sha='5bddb43f243e3cbb76504ecc38d8b0981e38866b7a4ea3b4557dcbbf3024712c'
if(-not(Test-Path -LiteralPath $raw -PathType Leaf)){throw 'RAW_MISSING'}
$gm=(Get-FileHash -LiteralPath $raw -Algorithm MD5).Hash.ToLowerInvariant()
$gs=(Get-FileHash -LiteralPath $raw -Algorithm SHA256).Hash.ToLowerInvariant()
if($gm-ne$md5 -or $gs-ne$sha){throw 'RAW_HASH_MISMATCH'}
$out=Join-Path $PWD 'machine1_reconstruct_next_611_620_20241202'
New-Item -ItemType Directory -Path $out -Force|Out-Null
$p=New-Object Microsoft.VisualBasic.FileIO.TextFieldParser($raw)
$p.TextFieldType=[Microsoft.VisualBasic.FileIO.FieldType]::Delimited
$p.SetDelimiters(',')
$p.HasFieldsEnclosedInQuotes=$true
try{
  $h=$p.ReadFields()
  $ti=[Array]::IndexOf($h,'RAW_TICKER'); $di=[Array]::IndexOf($h,'RAW_DATETIME_ISO')
  if($ti-lt0 -or $di-lt0){throw 'REQUIRED_HEADER_MISSING'}
  $agg=@{}; $row=0
  while(-not $p.EndOfData){
    $f=$p.ReadFields(); $row++
    if($f.Count-le [Math]::Max($ti,$di)){throw "SHORT_ROW_$row"}
    $dt=[string]$f[$di]
    if(-not $dt.StartsWith($date)){continue}
    $t=[string]$f[$ti]
    if([string]::IsNullOrWhiteSpace($t)){throw "EMPTY_TICKER_$row"}
    if(-not $agg.ContainsKey($t)){
      $agg[$t]=[ordered]@{ticker=$t;first=[int]$row;last=[int]$row;count=1;first_datetime=$dt;last_datetime=$dt}
    } else {
      $a=$agg[$t]; $a.last=[int]$row; $a.count=[int]$a.count+1; $a.last_datetime=$dt
    }
  }
} finally {$p.Close()}
[string[]]$tickers=@($agg.Keys); [Array]::Sort($tickers,[StringComparer]::Ordinal)
if($tickers.Count-ne892){throw "TICKER_CONTEXT_COUNT_$($tickers.Count)_EXPECTED_892"}
$anchors=@(
[pscustomobject]@{i=591;t='NINE';f=1165810;l=1165987;c=178;ft='09:00:00';lt='16:14:00';bl=39},
[pscustomobject]@{i=592;t='NISP';f=1168874;l=1169117;c=244;ft='09:00:00';lt='16:11:00';bl=40},
[pscustomobject]@{i=593;t='NOBU';f=1168066;l=1168107;c=42;ft='09:00:00';lt='16:00:00';bl=41},
[pscustomobject]@{i=594;t='NPGF';f=1168797;l=1168801;c=5;ft='09:55:00';lt='16:04:00';bl=42},
[pscustomobject]@{i=595;t='NRCA';f=1172638;l=1172686;c=49;ft='09:02:00';lt='16:00:00';bl=43},
[pscustomobject]@{i=596;t='NTBK';f=1173866;l=1173872;c=7;ft='10:07:00';lt='15:49:00';bl=44},
[pscustomobject]@{i=597;t='NZIA';f=1173945;l=1174028;c=84;ft='09:00:00';lt='16:00:00';bl=45},
[pscustomobject]@{i=598;t='OASA';f=1175455;l=1175603;c=149;ft='09:00:00';lt='16:09:00';bl=46},
[pscustomobject]@{i=599;t='OBMD';f=1177632;l=1177680;c=49;ft='09:00:00';lt='16:05:00';bl=47},
[pscustomobject]@{i=600;t='OILS';f=1178865;l=1178879;c=15;ft='09:00:00';lt='15:05:00';bl=48},
[pscustomobject]@{i=601;t='OKAS';f=1180292;l=1180349;c=58;ft='09:00:00';lt='16:10:00';bl=49},
[pscustomobject]@{i=602;t='OLIV';f=1181724;l=1181776;c=53;ft='09:00:00';lt='16:02:00';bl=50},
[pscustomobject]@{i=603;t='OMED';f=1182603;l=1182656;c=54;ft='09:00:00';lt='16:08:00';bl=51},
[pscustomobject]@{i=604;t='OMRE';f=1182594;l=1182594;c=1;ft='10:55:00';lt='10:55:00';bl=52},
[pscustomobject]@{i=605;t='OPMS';f=1183739;l=1183791;c=53;ft='09:00:00';lt='16:00:00';bl=53},
[pscustomobject]@{i=606;t='PACK';f=1184203;l=1184249;c=47;ft='09:00:00';lt='16:00:00';bl=54},
[pscustomobject]@{i=607;t='PADA';f=1184088;l=1184092;c=5;ft='09:55:00';lt='16:00:00';bl=55},
[pscustomobject]@{i=608;t='PADI';f=1184420;l=1184424;c=5;ft='09:55:00';lt='16:00:00';bl=56},
[pscustomobject]@{i=609;t='PALM';f=1184511;l=1184546;c=36;ft='09:02:00';lt='16:01:00';bl=57},
[pscustomobject]@{i=610;t='PAMG';f=1185757;l=1185789;c=33;ft='09:00:00';lt='16:00:00';bl=58})
$anchorProof=@()
foreach($x in $anchors){
  $t=$tickers[$x.i-1]; if($t-ne$x.t){throw "ANCHOR_TICKER_$($x.i)_$t"}
  $a=$agg[$t]; $ft=$a.first_datetime.Substring($a.first_datetime.Length-8); $lt=$a.last_datetime.Substring($a.last_datetime.Length-8)
  if($a.first-ne$x.f -or $a.last-ne$x.l -or $a.count-ne$x.c -or $ft-ne$x.ft -or $lt-ne$x.lt){throw "ANCHOR_DATA_$($x.i)_$t"}
  if(($x.i-552)-ne$x.bl){throw "ANCHOR_BUNDLE_REL_$($x.i)"}
  $anchorProof+=[pscustomobject]@{index=$x.i;ticker=$t;source_row_first=$a.first;source_row_last=$a.last;data_rows=$a.count;first_time=$ft;last_time=$lt;bundle_line=$x.bl;status='PASS'}
}
$next=@()
for($i=611;$i-le620;$i++){
  $t=$tickers[$i-1]; $a=$agg[$t]
  $ft=$a.first_datetime.Substring($a.first_datetime.Length-8); $lt=$a.last_datetime.Substring($a.last_datetime.Length-8)
  $next+=[pscustomobject][ordered]@{index=$i;ticker=$t;trading_date=$date;semantic_bundle='Raw Des 02-31-2024__SEMANTIC_0004.jsonl';bundle_line_number=($i-552);source_row_first=$a.first;source_row_last=$a.last;data_rows=$a.count;first_time=$ft;last_time=$lt;physical_line_first=($a.first+1);physical_line_last=($a.last+1)}
}
[ordered]@{status='PASS';method='RAW_CANONICAL_DETERMINISTIC_CONTEXT_RECONSTRUCTION';source_md5=$gm;source_sha256=$gs;trading_date=$date;total_ticker_context_paths=$tickers.Count;anchor_range='591-610';anchor_pass_count=$anchorProof.Count;anchor_required_count=20;bundle_line_relation='GLOBAL_INDEX_MINUS_552';anchors=$anchorProof;next_range='611-620';next=$next}|ConvertTo-Json -Depth 7|Set-Content -LiteralPath (Join-Path $out 'RECON_PROOF.json') -Encoding UTF8
$next|ConvertTo-Json -Depth 5|Set-Content -LiteralPath (Join-Path $out 'NEXT_611_620.json') -Encoding UTF8
Write-Host 'RECON PASS 892 contexts; anchors 20/20; emitted 611-620'
