# Publikowanie wydania

Poniższe kroki wykonuj w PowerShell z katalogu projektu. Nie przenoś istniejącego tagu
na inny commit — GitHub Actions wiąże uruchomienie z konkretnym SHA.

## 1. Sprawdzenie wersji

Wersja musi być identyczna w:

- `ha_windows_bridge/__init__.py`;
- `pyproject.toml`;
- `custom_components/ha_windows_bridge/manifest.json`;
- `installer/HAWindowsBridge.iss`.

## 2. Testy i budowanie

Wydanie niepodpisane:

```powershell
.\build.ps1 -Installer
```

Wydanie podpisane z certyfikatem z magazynu Windows:

```powershell
$env:HAWB_SIGNING_THUMBPRINT = "40_ZNAKOWY_ODCISK_CERTYFIKATU"
.\build.ps1 -Installer
Get-AuthenticodeSignature ".\dist\HA-Windows-Bridge-Setup-1.3.0.exe"
```

Prywatnego klucza i hasła do certyfikatu nigdy nie dodawaj do Git ani do plików
wydania.

## 3. Aktualizacja GitHub

```powershell
git status
git add .github assets brand custom_components ha_windows_bridge installer tests tools
git add README.md HOME_ASSISTANT_INTEGRATION.md CHANGELOG.md RELEASING.md
git add build.ps1 mqtt_volume.pyw pyproject.toml constraints.txt requirements.txt requirements-dev.txt
git commit -m "Release 1.3.0"
git push origin main
```

Poczekaj, aż workflow **Validate Home Assistant integration** dla gałęzi `main`
zakończy się powodzeniem. Następnie utwórz tag dokładnie na opublikowanym commicie:

```powershell
git tag -a v1.3.0 -m "HA Windows Bridge 1.3.0"
git push origin v1.3.0
```

Jeżeli tag `v1.3.0` już istnieje na złym commicie, usuń nieudane wydanie oraz tag na
GitHubie, usuń tag lokalny i utwórz go ponownie. Nie używaj force push do poprawiania
opublikowanego tagu.

## 4. Utworzenie Release

Na GitHubie otwórz **Releases → Draft a new release**, wybierz `v1.3.0`, ustaw tytuł
**HA Windows Bridge 1.3.0** i dołącz:

- `dist/HA-Windows-Bridge-Setup-1.3.0.exe`;
- `dist/HA-Windows-Bridge-1.3.0-win64.zip`;
- `dist/HA-Windows-Bridge-HA-Integration-1.3.0.zip`;
- `dist/SHA256SUMS-1.3.0.txt`.

Nie zaznaczaj **pre-release**, jeśli jest to stabilne wydanie. Po publikacji sprawdź
badge wydania w README oraz instalację HACS na czystym wpisie testowym.
