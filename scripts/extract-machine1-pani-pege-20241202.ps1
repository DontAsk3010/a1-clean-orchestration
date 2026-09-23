$ErrorActionPreference='Stop'
$raw='D:\TRADING SYSTEM\02_CURRENT_HISTORICAL_RAW_DATA_UJI\Raw Des 02-31-2024.csv'
$date='2024-12-02'
$md5='b8d42b35c90d2dff8b18ae4e1734523b'
$sha='5bddb43f243e3cbb76504ecc38d8b0981e38866b7a4ea3b4557dcbbf3024712c'
if(-not(Test-Path -LiteralPath $raw -PathType Leaf)){throw 'RAW_MISSING'}
$gm=(Get-FileHash -LiteralPath $raw -Algorithm MD5).Hash.ToLowerInvariant();$gs=(Get-FileHash -LiteralPath $raw -Algorithm SHA256).Hash.ToLowerInvariant()
if($gm-ne$md5 -or $gs-ne$sha){throw 'RAW_HASH_MISMATCH'}
$specs=@(
[pscustomobject]@{ticker='PANI';first=1187480;last=1187806;count=327;first_time='09:00:00';last_time='16:13:00';bundle_line=59},
[pscustomobject]@{ticker='PANR';first=1186153;last=1186257;count=105;first_time='09:00:00';last_time='16:12:00';bundle_line=60},
[pscustomobject]@{ticker='PANS';first=1186894;last=1186928;count=35;first_time='09:00:00';last_time='16:11:00';bundle_line=61},
[pscustomobject]@{ticker='PART';first=1193466;last=1193534;count=69;first_time='09:04:00';last_time='16:00:00';bundle_line=62},
[pscustomobject]@{ticker='PBID';first=1196074;last=1196156;count=83;first_time='09:00:00';last_time='16:13:00';bundle_line=63},
[pscustomobject]@{ticker='PBSA';first=1197587;last=1197693;count=107;first_time='09:00:00';last_time='16:04:00';bundle_line=64},
[pscustomobject]@{ticker='PCAR';first=1197333;last=1197334;count=2;first_time='10:09:00';last_time='13:31:00';bundle_line=65},
[pscustomobject]@{ticker='PDES';first=1197394;last=1197394;count=1;first_time='09:01:00';last_time='09:01:00';bundle_line=66},
[pscustomobject]@{ticker='PDPP';first=1199854;last=1199968;count=115;first_time='09:00:00';last_time='16:09:00';bundle_line=67},
[pscustomobject]@{ticker='PEGE';first=1201696;last=1201764;count=69;first_time='09:00:00';last_time='15:49:00';bundle_line=68})
$out=Join-Path $PWD 'machine1_pani_pege_20241202_evidence';New-Item -ItemType Directory -Path $out -Force|Out-Null
$map=@{};foreach($s in $specs){$map[$s.ticker]=New-Object System.Collections.Generic.List[object]}
$minFirst=($specs|Measure-Object first -Minimum).Minimum;$maxLast=($specs|Measure-Object last -Maximum).Maximum
$sr=New-Object IO.StreamReader($raw,[Text.Encoding]::UTF8,$true,1048576)
try{$hdr=$sr.ReadLine();$h=@($hdr.TrimStart([char]0xFEFF).Split(','));$pl=1;while(-not$sr.EndOfStream){$line=$sr.ReadLine();$pl++;$row=$pl-1;if($row-gt$maxLast){break};if($row-lt$minFirst){continue};foreach($s in $specs){if($row-ge$s.first -and $row-le$s.last){$x=$line|ConvertFrom-Csv -Header $h;$f=[ordered]@{};foreach($hh in $h){$f[$hh]=$x.$hh};$map[$s.ticker].Add([pscustomobject]@{source_row=[int]$row;physical_line=[int]$pl;raw_line=$line;fields=$f});break}}}}finally{$sr.Dispose()}
$proof=@();foreach($s in $specs){$a=$map[$s.ticker];if($a.Count-ne$s.count){throw "$($s.ticker)_COUNT got=$($a.Count) exp=$($s.count)"};for($i=0;$i-lt$a.Count;$i++){if($a[$i].source_row-ne($s.first+$i)){throw "$($s.ticker)_ROW"};if($a[$i].fields.RAW_TICKER-ne$s.ticker){throw "$($s.ticker)_TICKER"};if(-not([string]$a[$i].fields.RAW_DATETIME_ISO).StartsWith($date)){throw "$($s.ticker)_DATE"}};$fd=[string]$a[0].fields.RAW_DATETIME_ISO;$ld=[string]$a[$a.Count-1].fields.RAW_DATETIME_ISO;if($fd.Substring($fd.Length-8)-ne$s.first_time -or $ld.Substring($ld.Length-8)-ne$s.last_time){throw "$($s.ticker)_TIME"};[ordered]@{source_name=[IO.Path]::GetFileName($raw);source_md5=$gm;source_sha256=$gs;ticker=$s.ticker;trading_date=$date;semantic_bundle='Raw Des 02-31-2024__SEMANTIC_0004.jsonl';bundle_line_number=[int]$s.bundle_line;source_row_first=[int]$s.first;source_row_last=[int]$s.last;data_rows=[int]$s.count;first_datetime=$fd;last_datetime=$ld;header_line=$hdr;header_fields=$h;rows=$a}|ConvertTo-Json -Depth 8|Set-Content -LiteralPath (Join-Path $out "$($s.ticker)_20241202_PACKET.json") -Encoding UTF8;$rp=Join-Path $out "$($s.ticker)_20241202_ROWS.jsonl";if(Test-Path $rp){Remove-Item $rp -Force};foreach($rr in $a){($rr|ConvertTo-Json -Depth 6 -Compress)|Add-Content -LiteralPath $rp -Encoding UTF8};$proof+=[pscustomobject]@{ticker=$s.ticker;trading_date=$date;bundle_line_number=$s.bundle_line;source_row_first=$s.first;source_row_last=$s.last;data_rows=$s.count;first_datetime=$fd;last_datetime=$ld}}
[ordered]@{status='PASS';source_md5=$gm;source_sha256=$gs;trading_date=$date;tickers=$proof}|ConvertTo-Json -Depth 6|Set-Content -LiteralPath (Join-Path $out 'CHUNK_PROOF.json') -Encoding UTF8
