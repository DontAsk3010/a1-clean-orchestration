$ErrorActionPreference='Stop'
$raw='D:\TRADING SYSTEM\02_CURRENT_HISTORICAL_RAW_DATA_UJI\Raw Des 02-31-2024.csv'
$date='2024-12-02'
$md5='b8d42b35c90d2dff8b18ae4e1734523b'
$sha='5bddb43f243e3cbb76504ecc38d8b0981e38866b7a4ea3b4557dcbbf3024712c'
if(-not(Test-Path -LiteralPath $raw -PathType Leaf)){throw 'RAW_MISSING'}
$gm=(Get-FileHash -LiteralPath $raw -Algorithm MD5).Hash.ToLowerInvariant(); $gs=(Get-FileHash -LiteralPath $raw -Algorithm SHA256).Hash.ToLowerInvariant()
if($gm-ne$md5 -or $gs-ne$sha){throw 'RAW_HASH_MISMATCH'}
$specs=@(
[pscustomobject]@{ticker='OKAS';first=1180292;last=1180349;count=58;first_time='09:00:00';last_time='16:10:00';bundle_line=49},
[pscustomobject]@{ticker='OLIV';first=1181724;last=1181776;count=53;first_time='09:00:00';last_time='16:02:00';bundle_line=50},
[pscustomobject]@{ticker='OMED';first=1182603;last=1182656;count=54;first_time='09:00:00';last_time='16:08:00';bundle_line=51},
[pscustomobject]@{ticker='OMRE';first=1182594;last=1182594;count=1;first_time='10:55:00';last_time='10:55:00';bundle_line=52},
[pscustomobject]@{ticker='OPMS';first=1183739;last=1183791;count=53;first_time='09:00:00';last_time='16:00:00';bundle_line=53},
[pscustomobject]@{ticker='PACK';first=1184203;last=1184249;count=47;first_time='09:00:00';last_time='16:00:00';bundle_line=54},
[pscustomobject]@{ticker='PADA';first=1184088;last=1184092;count=5;first_time='09:55:00';last_time='16:00:00';bundle_line=55},
[pscustomobject]@{ticker='PADI';first=1184420;last=1184424;count=5;first_time='09:55:00';last_time='16:00:00';bundle_line=56},
[pscustomobject]@{ticker='PALM';first=1184511;last=1184546;count=36;first_time='09:02:00';last_time='16:01:00';bundle_line=57},
[pscustomobject]@{ticker='PAMG';first=1185757;last=1185789;count=33;first_time='09:00:00';last_time='16:00:00';bundle_line=58})
$out=Join-Path $PWD 'machine1_okas_pamg_20241202_evidence'; New-Item -ItemType Directory -Path $out -Force|Out-Null
$map=@{}; foreach($s in $specs){$map[$s.ticker]=New-Object System.Collections.Generic.List[object]}
$minFirst=($specs|Measure-Object first -Minimum).Minimum; $maxLast=($specs|Measure-Object last -Maximum).Maximum
$sr=New-Object IO.StreamReader($raw,[Text.Encoding]::UTF8,$true,1048576)
try{$hdr=$sr.ReadLine(); $h=@($hdr.TrimStart([char]0xFEFF).Split(',')); $pl=1; while(-not $sr.EndOfStream){$line=$sr.ReadLine();$pl++;$row=$pl-1;if($row-gt$maxLast){break};if($row-lt$minFirst){continue};foreach($s in $specs){if($row-ge$s.first -and $row-le$s.last){$x=$line|ConvertFrom-Csv -Header $h;$f=[ordered]@{};foreach($hh in $h){$f[$hh]=$x.$hh};$map[$s.ticker].Add([pscustomobject]@{source_row=[int]$row;physical_line=[int]$pl;raw_line=$line;fields=$f});break}}}}finally{$sr.Dispose()}
$proof=@(); foreach($s in $specs){$a=$map[$s.ticker];if($a.Count-ne$s.count){throw "$($s.ticker)_COUNT"};for($i=0;$i-lt$a.Count;$i++){if($a[$i].source_row-ne($s.first+$i)){throw "$($s.ticker)_ROW"};if($a[$i].fields.RAW_TICKER-ne$s.ticker){throw "$($s.ticker)_TICKER"};if(-not([string]$a[$i].fields.RAW_DATETIME_ISO).StartsWith($date)){throw "$($s.ticker)_DATE"}};$fd=[string]$a[0].fields.RAW_DATETIME_ISO;$ld=[string]$a[$a.Count-1].fields.RAW_DATETIME_ISO;if($fd.Substring($fd.Length-8)-ne$s.first_time -or $ld.Substring($ld.Length-8)-ne$s.last_time){throw "$($s.ticker)_TIME"};[ordered]@{source_name=[IO.Path]::GetFileName($raw);source_md5=$gm;source_sha256=$gs;ticker=$s.ticker;trading_date=$date;semantic_bundle='Raw Des 02-31-2024__SEMANTIC_0004.jsonl';bundle_line_number=[int]$s.bundle_line;source_row_first=[int]$s.first;source_row_last=[int]$s.last;data_rows=[int]$s.count;first_datetime=$fd;last_datetime=$ld;header_line=$hdr;header_fields=$h;rows=$a}|ConvertTo-Json -Depth 8|Set-Content (Join-Path $out "$($s.ticker)_20241202_PACKET.json") -Encoding UTF8;$rp=Join-Path $out "$($s.ticker)_20241202_ROWS.jsonl";foreach($rr in $a){($rr|ConvertTo-Json -Depth 6 -Compress)|Add-Content $rp -Encoding UTF8};$proof+=[pscustomobject]@{ticker=$s.ticker;source_row_first=$s.first;source_row_last=$s.last;data_rows=$s.count;first_datetime=$fd;last_datetime=$ld;bundle_line_number=$s.bundle_line}}
[ordered]@{status='PASS';source_md5=$gm;source_sha256=$gs;trading_date=$date;tickers=$proof}|ConvertTo-Json -Depth 6|Set-Content (Join-Path $out 'CHUNK_PROOF.json') -Encoding UTF8
