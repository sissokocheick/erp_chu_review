$ErrorActionPreference = 'Continue'
$share = '\\192.168.0.31\SAUV'

Write-Host "=== 1. Listage du partage ==="
try {
    $items = Get-ChildItem -Path $share -ErrorAction Stop | Select-Object -First 5
    Write-Host "LECTURE OK - element(s) visibles:"
    $items | ForEach-Object { Write-Host ("   " + $_.Name) }
} catch {
    Write-Host ("LECTURE IMPOSSIBLE : " + $_.Exception.Message)
}

Write-Host ""
Write-Host "=== 2. Test d'ecriture ==="
try {
    $t = New-Item -Path ($share + '\_test_erp.txt') -Value 'test acces ERP' -ItemType File -ErrorAction Stop
    Write-Host "ECRITURE OK"
    Remove-Item $t.FullName -Force
    Write-Host "SUPPRESSION OK"
} catch {
    Write-Host ("ECRITURE IMPOSSIBLE : " + $_.Exception.Message)
}

Write-Host ""
Write-Host "=== 3. Sessions SMB existantes vers 192.168.0.31 ==="
net use | Select-String "192.168.0.31"
