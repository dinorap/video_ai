CÁCH CÀI ĐẶT LẦN ĐẦU
B1. DI CHUYỂN VÀO THƯ MỤC DỰ ÁN

B2. CHẠY LẦN LƯỢT CÁC LỆNH SAU
python -m venv venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium

BƯỚC 3 ĐỂ MỞ APP CHẠY
python app.py

python build_fast_c++.py --dev
git add .; git commit -m 'ngon'; git push

python build_fast_c++.py --release --clean

# (tu dong tai ffmpeg vao dist/tools/ffmpeg/bin lan dau ~80MB)

python pack_release_update.py

# May moi: giai nen dist/VideoCreator hoac zip update — can co Google Chrome
