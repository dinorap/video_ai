import subprocess
import hashlib
import platform

def get_sys_info(command):
    """
    Hàm chạy lệnh PowerShell và lấy kết quả sạch
    """
    try:
        # Cờ để ẩn cửa sổ console đen khi chạy lệnh (quan trọng khi đóng gói exe)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        # Chạy lệnh PowerShell, dùng -NoProfile để nhanh hơn
        full_cmd = ["powershell", "-NoProfile", "-Command", command]
        
        output = subprocess.check_output(
            full_cmd, 
            startupinfo=startupinfo,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL
        ).decode("utf-8", errors="ignore").strip()
        
        return output
    except Exception:
        return None

def get_hwid():
    """
    Lấy HWID bằng PowerShell (Get-CimInstance) thay vì WMIC.
    Compatible: Windows 10, Windows 11.
    """
    if platform.system() != "Windows":
        return hashlib.md5(platform.node().encode()).hexdigest()

    try:
        # 1. Lấy UUID Mainboard
        # Lệnh cũ: wmic csproduct get uuid
        # Lệnh mới: (Get-CimInstance -Class Win32_ComputerSystemProduct).UUID
        uuid = get_sys_info("(Get-CimInstance -Class Win32_ComputerSystemProduct).UUID")

        # 2. Lấy Serial ổ cứng (Lấy ổ đầu tiên)
        # Lệnh cũ: wmic diskdrive get serialnumber
        # Lệnh mới: (Get-CimInstance -Class Win32_DiskDrive | Select-Object -First 1).SerialNumber
        disk_serial = get_sys_info("(Get-CimInstance -Class Win32_DiskDrive | Select-Object -First 1).SerialNumber")

        # Fallback: Nếu không lấy được UUID hoặc Disk (do quyền hạn), dùng tên máy
        if not uuid and not disk_serial:
            return hashlib.sha256(platform.node().encode()).hexdigest()
        
        # Xử lý chuỗi rỗng nếu một trong hai bị thiếu
        uuid = uuid if uuid else ""
        disk_serial = disk_serial if disk_serial else ""

        # 3. Hash lại
        raw_id = f"{uuid}-{disk_serial}"
        return hashlib.sha256(raw_id.encode()).hexdigest()

    except Exception as e:
        # Trường hợp xấu nhất: Lấy tên máy làm ID
        return hashlib.sha256(platform.node().encode()).hexdigest()

if __name__ == "__main__":
    print("HWID:", get_hwid())