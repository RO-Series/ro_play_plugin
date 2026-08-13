const bridge = window.AstrBotPluginPage;

const EVENTS = [
  ["join_review", "入群审核"], ["join_verify", "入群验证码"], ["blacklist", "黑白名单"],
  ["prohibited", "违禁检测"], ["talk_stats", "发言统计"], ["group_fire", "群聊续火"],
  ["friend_fire", "好友续火"], ["video_parse", "视频解析"], ["qa", "问答系统"],
  ["join_pm", "入群私聊"], ["leave_blacklist", "退群拉黑"], ["ban_notice", "禁言通知"],
  ["welcome", "入群欢迎"], ["leave_notice", "退群通知"], ["hourly_chime", "整点报时"],
  ["group_sign", "全群打卡"], ["fake_chat_declare", "伪造聊天声明"], ["self_title", "自助头衔"],
  ["red_packet_ban", "禁发红包"], ["member_care", "拍一拍记录"], ["invite_accept", "受邀入群自动同意"],
];

let current = {};

function render(events) {
  const box = document.getElementById("events");
  box.innerHTML = "";
  for (const [key, label] of EVENTS) {
    const row = document.createElement("label");
    row.className = "ev";
    row.innerHTML = `<input type="checkbox" data-key="${key}" ${events[key] ? "checked" : ""} /> ${label}`;
    box.appendChild(row);
  }
}

async function main() {
  await bridge.ready();
  const gid = prompt("请输入群号：");
  if (!gid) return;
  current = await bridge.apiGet("events/group?gid=" + encodeURIComponent(gid));
  document.getElementById("gid").textContent = "群 " + gid;
  render(current || {});

  document.getElementById("save").addEventListener("click", async () => {
    const events = {};
    document.querySelectorAll("input[type=checkbox]").forEach((el) => {
      events[el.dataset.key] = el.checked;
    });
    const res = await bridge.apiPost("events/group", { gid, events });
    document.getElementById("msg").textContent = res.ok ? "已保存" : "保存失败: " + (res.error || "");
  });
}

main().catch((e) => {
  document.getElementById("msg").textContent = "初始化失败: " + e;
});
