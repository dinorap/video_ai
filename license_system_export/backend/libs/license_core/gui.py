import customtkinter as ctk
import threading
import sys
import tkinter as tk # Dùng để lấy thông tin màn hình gốc nếu cần
import webbrowser
import os
import hashlib
import hmac

# Ưu tiên đọc config từ .env.enc, fallback .env cho môi trường dev.
try:
    BASE_DIR = os.path.dirname(__file__)
    from .env_secure import load_license_env
    load_license_env(BASE_DIR)
except Exception:
    pass

# --- CẤU HÌNH THEME ---
ctk.set_appearance_mode("Light")  # Light/Dark/System
ctk.set_default_color_theme("blue")

# Password để unlock setting
# Dùng hash để tránh lộ password trong binary khi build exe
# Để đổi password: hash password mới bằng SHA256, set vào biến môi trường ADMIN_PASSWORD_HASH (ưu tiên)
ADMIN_PASSWORD_HASH = (
    os.getenv("ADMIN_PASSWORD_HASH")
).strip()

def _verify_password(input_password: str) -> bool:
    """So sánh password an toàn bằng hash, tránh lộ password trong binary"""
    # Hash password input
    input_hash = hashlib.sha256(input_password.encode('utf-8')).hexdigest()
    # So sánh constant-time để chống timing attack
    return hmac.compare_digest(input_hash, ADMIN_PASSWORD_HASH)

class ModernLicenseUI:
    def __init__(self, guard, auto_close=True, allow_edit_server=True):
        self.guard = guard
        self.auto_close = auto_close
        self.allow_edit_server = allow_edit_server
        self.root = None
        self.is_loading = False
        self._offsetx = 0
        self._offsety = 0
        self._save_url_after_id = None
        self._config_unlocked = False  # Track xem đã unlock config chưa

    def show(self):
        # Khởi tạo cửa sổ CustomTkinter
        self.root = ctk.CTk()
        
        # Bỏ thanh tiêu đề Windows (Frameless)
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        
        # --- KÍCH THƯỚC & CĂN GIỮA ---
        # Tăng nhẹ chiều cao để form thoáng hơn (nhất là khi có status/error dài)
        w, h = 400, 460
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = (screen_w - w) // 2
        y = (screen_h - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        
        # Làm nền trong suốt để bo góc cửa sổ (Hack trick)
        self.root.configure(fg_color="#FFFFFF")

        # --- CONTAINER CHÍNH (Bo góc toàn bộ cửa sổ) ---
        # Main Frame đóng vai trò là cái nền cửa sổ
        self.main_frame = ctk.CTkFrame(self.root, corner_radius=20, fg_color="#ffffff", border_width=1, border_color="#e0e0e0")
        self.main_frame.pack(fill="both", expand=True)

        # Logic kéo thả cửa sổ (Bấm vào nền để kéo)
        self.main_frame.bind('<Button-1>', self._start_move)
        self.main_frame.bind('<B1-Motion>', self._on_move)

        # --- 1. NÚT ĐÓNG (Góc phải) ---
        self.btn_close = ctk.CTkButton(
            self.main_frame, text="✕", width=30, height=30,
            fg_color="transparent", text_color="#999999", hover_color="#ffebee",
            font=("Arial", 14), command=sys.exit
        )
        self.btn_close.pack(anchor="ne", padx=10, pady=(10, 0))

        # --- 2. HEADER ---
        # Icon Ổ khóa (Dùng Label text to)
        self.lbl_icon = ctk.CTkLabel(self.main_frame, text="🔒", font=("Segoe UI Emoji", 48), text_color="#4A90E2")
        self.lbl_icon.pack(pady=(0, 5))

        # Tiêu đề
        ctk.CTkLabel(self.main_frame, text="Kích Hoạt Bản Quyền", font=("Segoe UI", 20, "bold"), text_color="#333").pack()
        ctk.CTkLabel(
            self.main_frame,
            text="Vui lòng nhập License Key để tiếp tục sử dụng tool",
            font=("Segoe UI", 12),
            text_color="#777",
            wraplength=340,
        ).pack(pady=(2, 20))

        # --- 3. INPUT KEY (Giao diện Group: Icon + Entry) ---
        # Frame bao bên ngoài để tạo viền bo góc chung
        self.key_wrapper = ctk.CTkFrame(self.main_frame, fg_color="#F5F7FA", corner_radius=10, border_width=1, border_color="#E1E4E8")
        self.key_wrapper.pack(fill="x", padx=30, pady=(0, 10))

        # Icon Chìa khóa
        ctk.CTkLabel(self.key_wrapper, text="🔑", font=("Segoe UI Emoji", 16)).pack(side="left", padx=(15, 5), pady=10)

        # Ô nhập Key (Trong suốt để hòa vào nền Wrapper)
        self.entry_key = ctk.CTkEntry(
            self.key_wrapper, placeholder_text="Nhập License Key (XXXX-XXXX-...)",
            font=("Consolas", 13), border_width=0, fg_color="transparent", text_color="#333",
            height=35, width=200
        )
        self.entry_key.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        # Load key cũ
        saved_key = self.guard.storage.load_key_only()
        if saved_key: self.entry_key.insert(0, saved_key)
        self.entry_key.focus()

        # Thông báo thu thập thông tin bảo mật (IP/thiết bị/User-Agent)
        self.lbl_security_info = ctk.CTkLabel(
            self.main_frame,
            text="Khi kích hoạt, hệ thống sẽ thu thập IP, tên thiết bị và User-Agent để tăng cường bảo mật.",
            font=("Arial", 9),
            text_color="#777",
            wraplength=340,
            justify="left",
        )
        self.lbl_security_info.pack(anchor="w", padx=30, pady=(0, 8))

        # --- 4. CONFIG SERVER (Ẩn/Hiện) ---
        if self.allow_edit_server:
            # Frame chứa toàn bộ phần cấu hình URL, đặt ngay dưới ô key
            self.config_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
            self.config_frame.pack(fill="x", padx=30, pady=(0, 6))

            # Header: "Server URL" + nút thu gọn bên phải
            header_frame = ctk.CTkFrame(self.config_frame, fg_color="transparent")
            header_frame.pack(fill="x", pady=(0, 4))

            ctk.CTkLabel(
                header_frame,
                text="Server URL:",
                font=("Segoe UI", 11),
                text_color="#999",
                anchor="w",
            ).pack(side="left")

            self.btn_toggle = ctk.CTkLabel(
                header_frame,
                text="⚙️ Cấu hình",
                font=("Segoe UI", 10),
                text_color="#4A90E2",
                cursor="hand2",
            )
            self.btn_toggle.pack(side="right")
            self.btn_toggle.bind("<Button-1>", self._toggle_config)
            
            # Input URL Wrapper (bo góc + icon giống ô key)
            self.url_wrapper = ctk.CTkFrame(
                self.config_frame,
                fg_color="#F5F7FA",
                corner_radius=10,
                border_width=1,
                border_color="#E1E4E8",
            )

            ctk.CTkLabel(
                self.url_wrapper,
                text="🌐",
                font=("Segoe UI Emoji", 14),
                text_color="#777",
            ).pack(side="left", padx=(10, 6), pady=6)
            
            self.entry_url = ctk.CTkEntry(
                self.url_wrapper,
                font=("Consolas", 11),
                border_width=0,
                fg_color="transparent",
                text_color="#555",
                height=30,
                placeholder_text="https://license.nanoproai.shop",
            )
            self.entry_url.pack(side="left", fill="x", expand=True, padx=(0, 10), pady=6)
            self.entry_url.insert(0, self.guard.server_url)

            # Auto-save server URL khi gõ/thoát ô nhập (không cần bấm nút)
            # - Debounce để tránh ghi file liên tục
            self.entry_url.bind("<KeyRelease>", lambda _e: self._schedule_save_server_url())
            self.entry_url.bind("<FocusOut>", lambda _e: self._save_server_url_if_changed())
            
            # Ẩn url_wrapper mặc định (chỉ hiện khi đã unlock)
            self.url_wrapper.pack_forget()
        else:
             self.entry_url = ctk.CTkEntry(self.root) # Dummy

        # --- 5. NÚT KÍCH HOẠT ---
        self.btn_active = ctk.CTkButton(
            self.main_frame, text="KÍCH HOẠT NGAY", font=("Segoe UI", 13, "bold"),
            fg_color="#4A90E2", hover_color="#357ABD", text_color="white",
            corner_radius=10, height=45,
            command=self._on_click_active
        )
        self.btn_active.pack(fill="x", padx=30, pady=(0, 10))

        # --- 6. STATUS (Toast) ---
        self.lbl_status = ctk.CTkLabel(self.main_frame, text="", font=("Segoe UI", 12), text_color="#ff5252")
        self.lbl_status.pack(pady=(0, 15))

        # Bind Enter
        self.root.bind('<Return>', lambda e: self._on_click_active())
        self.root.mainloop()

    # --- LOGIC KÉO THẢ & XỬ LÝ ---
    def _start_move(self, event):
        self._offsetx = event.x
        self._offsety = event.y

    def _on_move(self, event):
        x = self.root.winfo_pointerx() - self._offsetx
        y = self.root.winfo_pointery() - self._offsety
        self.root.geometry(f'+{x}+{y}')

    def _toggle_config(self, event):
        # Nếu chưa unlock, yêu cầu nhập password
        if not self._config_unlocked:
            self._show_password_dialog()
            return
        
        # Ẩn/hiện riêng phần ô nhập URL, header vẫn giữ chỗ để URL gần với ô key
        if self.url_wrapper.winfo_ismapped():
            self.url_wrapper.pack_forget()
            self.btn_toggle.configure(text="⚙️ Cấu hình")
        else:
            self.url_wrapper.pack(fill="x")
            self.btn_toggle.configure(text="▲ Thu gọn")
    
    def _show_password_dialog(self):
        """Hiện dialog yêu cầu nhập password admin"""
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("Xác thực Admin")
        dialog.geometry("350x180")
        dialog.attributes('-topmost', True)
        dialog.transient(self.root)
        
        # Căn giữa dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (350 // 2)
        y = (dialog.winfo_screenheight() // 2) - (180 // 2)
        dialog.geometry(f"350x180+{x}+{y}")
        
        # Frame chính
        main_frame = ctk.CTkFrame(dialog, corner_radius=15)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Tiêu đề
        ctk.CTkLabel(
            main_frame,
            text="🔒 Yêu cầu xác thực",
            font=("Segoe UI", 16, "bold"),
            text_color="#333"
        ).pack(pady=(15, 5))
        
        ctk.CTkLabel(
            main_frame,
            text="Nhập mật khẩu Admin để mở cấu hình",
            font=("Segoe UI", 11),
            text_color="#666"
        ).pack(pady=(0, 15))
        
        # Ô nhập password
        entry_pass = ctk.CTkEntry(
            main_frame,
            placeholder_text="Nhập mật khẩu...",
            font=("Consolas", 12),
            width=250,
            show="*"  # Ẩn ký tự
        )
        entry_pass.pack(pady=(0, 10))
        entry_pass.focus()
        
        # Label thông báo lỗi
        lbl_error = ctk.CTkLabel(
            main_frame,
            text="",
            font=("Segoe UI", 10),
            text_color="#ff5252"
        )
        lbl_error.pack()
        
        def check_password():
            password = entry_pass.get().strip()
            if _verify_password(password):
                self._config_unlocked = True
                self.url_wrapper.pack(fill="x")
                self.btn_toggle.configure(text="▲ Thu gọn")
                dialog.destroy()
            else:
                lbl_error.configure(text="❌ Mật khẩu sai!")
                entry_pass.delete(0, tk.END)
        
        # Nút xác nhận
        btn_ok = ctk.CTkButton(
            main_frame,
            text="Xác nhận",
            command=check_password,
            width=120,
            height=35
        )
        btn_ok.pack(pady=(5, 10))
        
        # Bind Enter
        entry_pass.bind('<Return>', lambda e: check_password())
        
        # Nút hủy
        btn_cancel = ctk.CTkButton(
            main_frame,
            text="Hủy",
            command=dialog.destroy,
            fg_color="transparent",
            text_color="#999",
            width=120,
            height=30
        )
        btn_cancel.pack()

    def _show_toast(self, msg, type="info"):
        color_map = {"success": "#27ae60", "error": "#ff5252", "info": "#4A90E2"}
        self.lbl_status.configure(text=msg, text_color=color_map.get(type, "#333"))

    def _open_store_page(self):
        try:
            base = (getattr(self.guard, "server_url", "") or "").strip().rstrip("/")
            if not base:
                base = "https://license.nanoproai.shop"
            webbrowser.open(f"{base}/store.html")
        except Exception:
            # Không để lỗi mở browser làm crash UI
            self._show_toast("Không mở được trình duyệt. Vui lòng copy link server/store.html", "error")

    def _schedule_save_server_url(self, delay_ms: int = 400):
        """
        Debounce: đợi một chút sau khi user gõ rồi mới lưu.
        """
        if not self.allow_edit_server:
            return
        if not self.root:
            return

        try:
            if self._save_url_after_id is not None:
                self.root.after_cancel(self._save_url_after_id)
        except Exception:
            pass

        self._save_url_after_id = self.root.after(delay_ms, self._save_server_url_if_changed)

    def _save_server_url_if_changed(self):
        """
        Lưu URL nếu user đã sửa. Không yêu cầu bấm nút KÍCH HOẠT.
        """
        if not self.allow_edit_server:
            return
        try:
            if self._save_url_after_id is not None and self.root:
                try:
                    self.root.after_cancel(self._save_url_after_id)
                except Exception:
                    pass
            self._save_url_after_id = None

            new_url = (self.entry_url.get() or "").strip().rstrip("/")
            if not new_url:
                return

            current = (getattr(self.guard, "server_url", "") or "").strip().rstrip("/")
            if new_url == current:
                return

            # Cập nhật URL trong guard và lưu để lần sau mở tool giữ nguyên
            self.guard.server_url = new_url
            try:
                self.guard.storage.save_server_url(self.guard.server_url)
                # Không spam toast khi user gõ, chỉ báo nhẹ nếu muốn:
                # self._show_toast("💾 Đã lưu Server URL", "success")
            except Exception:
                pass
        except Exception:
            # Không để lỗi lưu config làm crash UI
            pass

    def _on_click_active(self):
        if self.is_loading: return
        key = self.entry_key.get().strip().upper()
        
        if self.allow_edit_server:
            # Đảm bảo URL đang hiển thị được lưu (trường hợp user paste rồi bấm ngay)
            self._save_server_url_if_changed()

        if not key:
            self._show_toast("Vui lòng nhập License Key", "error")
            return

        self.is_loading = True
        self.btn_active.configure(text="⏳ ĐANG XỬ LÝ...", state="disabled", fg_color="#999")
        self._show_toast("Đang kết nối server...", "info")
        
        threading.Thread(target=self._run_thread, args=(key,), daemon=True).start()

    def _run_thread(self, key):
        try:
            ok, msg = self.guard.activate(key)
            self.root.after(0, self._done, ok, msg)
        except Exception as e:
            self.root.after(0, self._done, False, str(e))

    def _done(self, ok, msg):
        self.is_loading = False
        if ok:
            self._show_toast(f"✔ {msg}", "success")
            self.entry_key.configure(state="disabled")
            if self.allow_edit_server: self.entry_url.configure(state="disabled")
            self.btn_active.configure(text="ĐÃ KÍCH HOẠT", fg_color="#27ae60", state="disabled")
            if self.auto_close:
                self.root.after(1500, self.root.destroy)
        else:
            self._show_toast(msg, "error")
            self.btn_active.configure(text="THỬ LẠI", fg_color="#4A90E2", state="normal")