const bridge = window.AstrBotPluginPage;

async function main() {
  await bridge.ready();
  const cfg = await bridge.apiGet("config");

  document.getElementById("owner_qqs").value = cfg.owner_qqs || "";
  document.getElementById("legacy_no_prefix").checked = !!cfg.legacy_no_prefix;
  document.getElementById("html_render_enabled").checked = !!cfg.html_render_enabled;
  document.getElementById("music_source").value = cfg.music_source || "汽水";

  document.getElementById("save").addEventListener("click", async () => {
    const body = {
      owner_qqs: document.getElementById("owner_qqs").value.trim(),
      legacy_no_prefix: document.getElementById("legacy_no_prefix").checked,
      html_render_enabled: document.getElementById("html_render_enabled").checked,
      music_source: document.getElementById("music_source").value,
    };
    const res = await bridge.apiPost("config", body);
    const msg = document.getElementById("msg");
    msg.textContent = res.ok ? "已保存，点击「重载插件」生效" : "保存失败: " + (res.error || "");
  });

  document.getElementById("reload").addEventListener("click", () => {
    const msg = document.getElementById("msg");
    msg.textContent = "请在插件管理页手动重载插件（配置保存后需重载生效）";
  });
}

main().catch((e) => {
  document.getElementById("msg").textContent = "页面初始化失败: " + e;
});
