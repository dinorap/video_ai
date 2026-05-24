// composables/useLicense.ts
import { ref, computed } from "vue";

const API_BASE = "http://localhost:8000"; // Thay đổi theo API base URL của bạn

// UI mode theo license (1: all, 2: url+custom, 3: comic+story)
const licenseUiMode = ref<1 | 2 | 3>(1);

// YouTube plan (standard, pro, pro_plus)
const licenseYtPlan = ref<"standard" | "pro" | "pro_plus">("standard");

let _licenseUiModeLoaded = false;

/**
 * Lấy thông tin license từ server (ui_mode + yt_plan)
 */
async function fetchLicenseInfo() {
    if (_licenseUiModeLoaded) return;
    _licenseUiModeLoaded = true;

    try {
        const res = await fetch(`${API_BASE}/api/license/info`);
        if (!res.ok) throw new Error("Không lấy được license info");

        const data = await res.json();
        const mode = Number(data?.ui_mode ?? 1);
        licenseUiMode.value = mode === 2 || mode === 3 ? (mode as 2 | 3) : 1;

        const plan = String(data?.yt_plan ?? "standard").toLowerCase();
        licenseYtPlan.value =
            plan === "pro_plus"
                ? "pro_plus"
                : plan === "pro"
                    ? "pro"
                    : "standard";
    } catch (err) {
        console.error("Lỗi lấy license info:", err);
        // Fallback an toàn: hiển thị all
        licenseUiMode.value = 1;
        licenseYtPlan.value = "standard";
    }
}

/**
 * Lấy trạng thái license hiện tại (key, ok, expire_at, ui_mode, yt_plan)
 */
async function fetchLicenseStatus() {
    try {
        const res = await fetch(`${API_BASE}/api/license/status`);
        if (!res.ok) throw new Error("Không lấy được license status");

        const data = await res.json();
        return {
            license_key: data.license_key || "",
            ok: Boolean(data.ok),
            expire_at: data.expire_at || null,
            ui_mode: data.ui_mode || 1,
            yt_plan: data.yt_plan || "standard",
        };
    } catch (err) {
        console.error("Lỗi lấy license status:", err);
        return null;
    }
}

/**
 * Kích hoạt license key mới
 */
async function activateLicense(licenseKey: string) {
    try {
        const res = await fetch(`${API_BASE}/api/license/activate`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ license_key: licenseKey.trim() }),
        });

        const data = await res.json();

        if (res.ok && data.ok) {
            // Cập nhật ui_mode và yt_plan sau khi activate thành công
            if (data.ui_mode) {
                const mode = Number(data.ui_mode);
                licenseUiMode.value = mode === 2 || mode === 3 ? (mode as 2 | 3) : 1;
            }
            if (data.yt_plan) {
                const plan = String(data.yt_plan).toLowerCase();
                licenseYtPlan.value =
                    plan === "pro_plus"
                        ? "pro_plus"
                        : plan === "pro"
                            ? "pro"
                            : "standard";
            }
            return { ok: true, message: data.message || "Kích hoạt thành công!" };
        } else {
            return {
                ok: false,
                message: data.message || data.detail || "Kích hoạt thất bại!",
            };
        }
    } catch (err: any) {
        return { ok: false, message: `Lỗi kết nối: ${err.message}` };
    }
}

/**
 * Computed: Danh sách subtabs được phép hiển thị theo license
 */
const enabledSubTabs = computed<Array<"url" | "custom" | "comic" | "story">>(
    () => {
        if (licenseUiMode.value === 2) return ["url", "custom"];
        if (licenseUiMode.value === 3) return ["comic", "story"];
        return ["url", "custom", "comic", "story"];
    }
);

/**
 * Computed: Danh sách main tabs được phép hiển thị theo license
 */
const enabledMainTabs = computed<
    Array<"youtube" | "ai" | "youtube_new" | "ai_new">
>(() => {
    // Ví dụ: Chỉ khi có Pro+ plan thì mới hiện đủ 4 tabs
    if (licenseYtPlan.value === "pro_plus") {
        return ["youtube", "ai", "youtube_new", "ai_new"];
    }
    // Pro: chỉ hiện 2 tabs cũ
    if (licenseYtPlan.value === "pro") {
        return ["youtube", "ai"];
    }
    // Standard: chỉ hiện 1 tab
    return ["youtube"];
});

export function useLicense() {
    return {
        licenseUiMode,
        licenseYtPlan,
        enabledSubTabs,
        enabledMainTabs,
        fetchLicenseInfo,
        fetchLicenseStatus,
        activateLicense,
    };
}
