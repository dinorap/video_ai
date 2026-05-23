# Build & Release

## Buoc 1 — Build Nuitka

```powershell
python build_fast_c++.py --release --clean
```

Output: `dist\VideoCreator\` (exe + config + templaces...)

## Buoc 2 — Dong goi update (file rieng)

```powershell
python pack_release_update.py
```

Tao: `VideoCreator.zip` + `update.json` (zip toan bo `dist/VideoCreator`, **khong** gom `config/` `storage/`)

## Upload GitHub

https://github.com/dinorap/video-release/releases/new  
Tag = `version.py` → `CURRENT_VERSION`  
Upload: `VideoCreator.zip` + `update.json`
