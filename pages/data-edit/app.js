const bridge = window.AstrBotPluginPage;

async function main() {
  await bridge.ready();

  document.getElementById("load").addEventListener("click", async () => {
    const uid = document.getElementById("uid").value.trim();
    if (!uid) { document.getElementById("msg").textContent = "请输入 QQ 号"; return; }
    const data = await bridge.apiGet("data-edit?uid=" + encodeURIComponent(uid));
    if (!data.ok) { document.getElementById("msg").textContent = "加载失败: " + (data.error || ""); return; }
    document.getElementById("money").value = data.money;
    document.getElementById("bait").value = data.bait;
    document.getElementById("bank").value = data.bank;
    document.getElementById("msg").textContent = "已加载玩家 " + uid + " 的数据";
  });

  document.getElementById("save").addEventListener("click", async () => {
    const uid = document.getElementById("uid").value.trim();
    if (!uid) { document.getElementById("msg").textContent = "请输入 QQ 号"; return; }
    const body = {
      uid,
      money: parseInt(document.getElementById("money").value, 10) || 0,
      bait: parseInt(document.getElementById("bait").value, 10) || 0,
      bank: parseInt(document.getElementById("bank").value, 10) || 0,
    };
    const res = await bridge.apiPost("data-edit", body);
    document.getElementById("msg").textContent = res.ok ? "已保存" : "保存失败: " + (res.error || "");
  });
}

main().catch((e) => {
  document.getElementById("msg").textContent = "初始化失败: " + e;
});
