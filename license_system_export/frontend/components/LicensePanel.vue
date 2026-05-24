<template>
  <div class="license-panel">
    <div class="license-header">
      <h3>🔐 License Key</h3>
    </div>

    <div class="license-status" v-if="licenseInfo">
      <div class="status-badge" :class="licenseInfo.ok ? 'active' : 'inactive'">
        {{ licenseInfo.ok ? "✅ Đã kích hoạt" : "❌ Chưa kích hoạt" }}
      </div>
      <div v-if="licenseInfo.expire_at" class="expire-info">
        Hạn sử dụng: {{ licenseInfo.expire_at }}
      </div>
    </div>

    <div class="license-form">
      <div class="field">
        <label>License Key</label>
        <input
          type="text"
          class="input"
          v-model="newLicenseKey"
          placeholder="Nhập license key (XXXX-XXXX-...)"
          :disabled="isActivating"
        />
      </div>

      <button
        class="btn btn-primary"
        @click="activateLicense"
        :disabled="isActivating || !newLicenseKey.trim()"
      >
        {{ isActivating ? "Đang kích hoạt..." : "Kích hoạt" }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from "vue";
import { useToast } from "vue-toastification";

const toast = useToast();
const API_BASE = "http://localhost:8000";

const licenseInfo = ref<{
  license_key: string;
  ok: boolean;
  expire_at: string | null;
} | null>(null);

const newLicenseKey = ref("");
const isActivating = ref(false);

async function fetchLicenseStatus() {
  try {
    const res = await fetch(`${API_BASE}/api/license/status`);
    if (!res.ok) return;
    const data = await res.json();
    licenseInfo.value = {
      license_key: data.license_key || "",
      ok: Boolean(data.ok),
      expire_at: data.expire_at || null,
    };
    // Mặc định hiển thị key hiện tại trong ô input để user có thể sửa
    newLicenseKey.value = licenseInfo.value.license_key;
  } catch (e) {
    console.error("Lỗi lấy license status:", e);
  }
}

async function activateLicense() {
  if (!newLicenseKey.value.trim()) {
    toast.error("Vui lòng nhập license key");
    return;
  }

  isActivating.value = true;
  try {
    const res = await fetch(`${API_BASE}/api/license/activate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ license_key: newLicenseKey.value.trim() }),
    });

    const data = await res.json();

    if (res.ok && data.ok) {
      toast.success(data.message || "Đã kích hoạt license thành công!");
      await fetchLicenseStatus();
    } else {
      toast.error(data.message || data.detail || "Kích hoạt license thất bại!");
    }
  } catch (e: any) {
    toast.error(`Lỗi kết nối: ${e.message}`);
  } finally {
    isActivating.value = false;
  }
}

onMounted(() => {
  fetchLicenseStatus();
});
</script>

<style scoped>
.license-panel {
  background: rgba(255, 255, 255, 0.05);
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 20px;
}

.license-header h3 {
  margin: 0 0 15px 0;
  color: #fff;
  font-size: 16px;
  font-weight: 600;
}

.license-status {
  margin-bottom: 15px;
}

.status-badge {
  display: inline-block;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 8px;
}

.status-badge.active {
  background: rgba(46, 213, 115, 0.2);
  color: #2ed573;
  border: 1px solid rgba(46, 213, 115, 0.3);
}

.status-badge.inactive {
  background: rgba(255, 71, 87, 0.2);
  color: #ff4757;
  border: 1px solid rgba(255, 71, 87, 0.3);
}

.expire-info {
  color: rgba(255, 255, 255, 0.7);
  font-size: 12px;
}

.license-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field label {
  color: rgba(255, 255, 255, 0.8);
  font-size: 13px;
  font-weight: 500;
}

.input {
  width: 100%;
  padding: 10px 12px;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  color: #fff;
  font-size: 13px;
  font-family: "Consolas", monospace;
  transition: all 0.2s;
}

.input:focus {
  outline: none;
  border-color: rgba(74, 144, 226, 0.5);
  background: rgba(255, 255, 255, 0.12);
}

.input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn {
  padding: 10px 16px;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-primary {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
}

.btn-primary:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
