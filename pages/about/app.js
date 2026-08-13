const bridge = window.AstrBotPluginPage;

async function main() {
  await bridge.ready();
  const info = await bridge.apiGet("about");
  document.getElementById("ver").textContent = "版本 " + (info.version || "1.0.0");
  document.getElementById("desc").textContent = info.desc || "";
}

main().catch(() => {
  document.getElementById("ver").textContent = "版本信息加载失败";
});
