"""前端远控入口与 C1 接线门禁。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FE = ROOT / "autopilot_platform" / "frontend" / "src"
DOCS = ROOT / "docs" / "architecture"


def test_product_surface_c1_unfrozen():
    text = (DOCS / "PRODUCT_SURFACE_AND_REFERENCE_PLAN.md").read_text(encoding="utf-8")
    assert "DEVICE_REMOTE_ANDROID_MVP" in text
    assert "已书面解冻" in text or "UNFROZEN" in text
    assert (DOCS / "DEVICE_REMOTE_ANDROID_MVP.md").is_file()


def test_remote_files_panel_componentized():
    files_dir = FE / "components" / "remote" / "files"
    assert (files_dir / "RemoteFileToolbar.vue").is_file()
    assert (files_dir / "RemoteFileTreeList.vue").is_file()
    assert (files_dir / "RemoteFileFlatList.vue").is_file()
    assert (files_dir / "RemoteFilePreviewModal.vue").is_file()
    assert (files_dir / "RemoteFileUploadBar.vue").is_file()
    panel = (FE / "components" / "remote" / "RemoteFilesPanel.vue").read_text(
        encoding="utf-8"
    )
    assert "RemoteFileTreeList" in panel
    assert "RemoteFilePreviewModal" in panel
    assert "RemoteFileFlatList" not in panel
    assert "parseIosFsyncTree" in (
        FE / "composables" / "remote" / "files" / "parseIosFsyncTree.ts"
    ).read_text(encoding="utf-8")
    assert 'iosApp.value ? "/Documents"' in panel
    assert 'next ? "/Documents"' in panel
    composable = (FE / "composables" / "remote" / "useRemoteFiles.ts").read_text(
        encoding="utf-8"
    )
    assert "treeNodes" in composable
    assert "androidTreeNodes" in composable
    assert "listAndroidTree" in composable
    assert "pullForPreview" in composable
    assert "transferPhase" in composable
    assert (FE / "composables" / "remote" / "files" / "remoteUploadPath.ts").is_file()
    upload_bar = (files_dir / "RemoteFileUploadBar.vue").read_text(encoding="utf-8")
    assert "上传目标" not in upload_bar
    assert "正在写入设备" in upload_bar
    assert (FE / "composables" / "remote" / "remoteFilePull.ts").is_file()
    preview = (FE / "components" / "remote" / "files" / "RemoteFilePreviewModal.vue").read_text(
        encoding="utf-8"
    )
    assert "fetchPreviewBlob" in preview or "fetch-preview-blob" in preview
    assert "RemoteFileIconBtn" in (
        FE / "components" / "remote" / "files" / "RemoteFileTreeList.vue"
    ).read_text(encoding="utf-8")
    assert (FE / "components" / "remote" / "files" / "RemoteFileIosAppSelector.vue").is_file()
    ios_sel = (
        FE / "components" / "remote" / "files" / "RemoteFileIosAppSelector.vue"
    ).read_text(encoding="utf-8")
    assert "ApSelect" in ios_sel
    assert "<select" not in ios_sel
    ios_ops = (
        ROOT / "autopilot_platform" / "runner" / "remote" / "ios" / "file_ops.py"
    ).read_text(encoding="utf-8")
    assert "def mkdir(" in ios_ops
    assert "def delete(" in ios_ops
    assert "def rename(" in ios_ops
    ios_dispatch = (
        ROOT / "autopilot_platform" / "runner" / "remote" / "ios" / "command_dispatch.py"
    ).read_text(encoding="utf-8")
    assert 'command == "file.mkdir"' in ios_dispatch
    assert 'command == "file.delete"' in ios_dispatch
    assert 'command == "accessibility"' in ios_dispatch
    assert "filesharing" in (
        ROOT / "autopilot_platform" / "runner" / "remote" / "ios" / "app_ops.py"
    ).read_text(encoding="utf-8")
    transfer = (
        ROOT / "autopilot_platform" / "runner" / "remote" / "android" / "file_transfer.py"
    ).read_text(encoding="utf-8")
    assert "event.get(\"install\")" in transfer


def test_remote_dialog_and_composables_exist():
    assert (FE / "components" / "RemoteDeviceDialog.vue").is_file()
    assert (FE / "composables" / "useRemoteSession.ts").is_file()
    dialog = (FE / "components" / "RemoteDeviceDialog.vue").read_text(encoding="utf-8")
    assert "RTCPeerConnection" in dialog
    assert dialog.find("const readonlySession") < dialog.find("const stageStreaming")
    assert "postSignaling" in dialog
    assert "pollSignaling" in dialog
    assert "pollMedia" in dialog
    assert "prefersMjpeg" in dialog
    assert "function emitTo(" in dialog
    assert "emitInputFallback" in dialog
    assert "needsSignalingDrain" in dialog or "drainSignaling" in dialog
    assert "apiPostRemoteCommand" in dialog
    stream_panel = (FE / "components" / "remote" / "RemoteStreamPanel.vue").read_text(
        encoding="utf-8"
    )
    assert "STREAM_LIMITS" in stream_panel
    stream_ts = (FE / "composables" / "remote" / "useRemoteStream.ts").read_text(
        encoding="utf-8"
    )
    assert "clampForm" in stream_ts
    assert "500_000" in stream_ts
    assert "setOverlayBusy" in dialog
    assert "STATUS_WATCH_CONNECTED_MS" in dialog
    stage = (FE / "components" / "remote" / "RemoteStage.vue").read_text(encoding="utf-8")
    assert "@wheel.prevent=\"handleWheel\"" in stage
    assert "readSurfaceRect" in stage
    assert "remote-video-wrap" in stage
    assert "remote-stage-placeholder" in stage
    assert "remote-placeholder-spinner" in stage
    assert "placeholderTitle" in stage
    clipboard = (FE / "components" / "remote" / "RemoteClipboardPanel.vue").read_text(
        encoding="utf-8"
    )
    assert "remote-clipboard-action-grid--phone" in clipboard
    drawer = (FE / "components" / "remote" / "RemoteSideDrawer.vue").read_text(
        encoding="utf-8"
    )
    assert "设备信息" in drawer
    assert "参与者" not in drawer
    assert "RemoteDeviceInfoPanel" in drawer
    assert "RemoteDeviceLogPanel" in drawer
    assert "RemoteDiagnosticsPanel" not in drawer
    assert '["logs", "日志"]' in drawer
    assert "诊断" not in drawer.split("const tabs =", 1)[1].split("] as const", 1)[0]
    assert "会话状态" in stream_panel
    assert "质量状态" in stream_panel
    assert "RemoteViewersPanel" not in drawer
    assert (FE / "components" / "remote" / "RemoteDeviceInfoPanel.vue").is_file()
    assert (FE / "composables" / "remote" / "useRemoteDeviceLogs.ts").is_file()
    assert (FE / "components" / "remote" / "RemoteDeviceLogPanel.vue").is_file()
    logs_ts = (FE / "composables" / "remote" / "useRemoteDeviceLogs.ts").read_text(
        encoding="utf-8"
    )
    assert "EventSource" in logs_ts
    assert "apiCreateDeviceLogStreamToken" in logs_ts
    assert "new EventSource" in logs_ts
    assert "onMounted" in logs_ts
    assert "MAX_RECONNECT" in logs_ts
    assert "RECONNECT_MS" in logs_ts
    assert "copyLines" in logs_ts
    assert "onBeforeUnmount" in logs_ts
    assert "stopStream" in logs_ts
    log_panel = (FE / "components" / "remote" / "RemoteDeviceLogPanel.vue").read_text(
        encoding="utf-8"
    )
    assert "暂停" in log_panel
    assert "复制" in log_panel
    assert "自动换行" in log_panel
    assert "自动滚动" in log_panel
    assert "详细 · Verbose (V)" in logs_ts
    assert "调试 · Debug (D)" in logs_ts
    assert "信息 · Info (I)" in logs_ts
    assert "警告 · Warning (W)" in logs_ts
    assert "错误 · Error (E)" in logs_ts
    assert "致命 · Fatal (F)" in logs_ts
    assert "默认 · Default" in logs_ts
    assert ':disabled="!sessionReady"' in log_panel
    assert "ApSelect" in log_panel
    assert "<select" not in log_panel
    assert ':disabled="!streaming"' not in log_panel
    assert "logcat-${id}-${stamp}.txt" in logs_ts
    assert "syslog-${id.slice(0, 8)}-${Date.now()}.log" in logs_ts
    assert "ANDROID_THREADTIME" in logs_ts
    assert "remote-log-line" in log_panel
    assert "line.raw" in log_panel
    assert 'v-else-if="active === \'logs\'"' in drawer
    assert (FE / "components" / "remote" / "RemoteDiagnosticsPanel.vue").is_file() is False
    assert (FE / "composables" / "remote" / "useRemoteDeviceInfo.ts").is_file()
    info_panel = (FE / "components" / "remote" / "RemoteDeviceInfoPanel.vue").read_text(
        encoding="utf-8"
    )
    assert "wifi_ssid" not in info_panel
    assert "rdi-meter" in info_panel
    assert "prefetch" in drawer
    assert "remoteStreamControlReady" in drawer
    info_ts = (FE / "composables" / "remote" / "useRemoteDeviceInfo.ts").read_text(
        encoding="utf-8"
    )
    assert "25_000" in info_ts
    assert "waitForRemoteStreamControl" in info_ts
    android_session = (
        ROOT / "autopilot_platform" / "runner" / "remote" / "android" / "session.py"
    ).read_text(encoding="utf-8")
    ios_session = (
        ROOT / "autopilot_platform" / "runner" / "remote" / "ios" / "session.py"
    ).read_text(encoding="utf-8")
    assert "normalize_reliable_command" in android_session
    assert "normalize_reliable_command" in ios_session
    android_info = (
        ROOT / "autopilot_platform" / "runner" / "remote" / "android" / "device_info.py"
    ).read_text(encoding="utf-8")
    assert "dumpsys wifi 2>/dev/null" not in android_info
    assert "useRemoteClipboard" in clipboard
    clip_ts = (FE / "composables" / "remote" / "useRemoteClipboard.ts").read_text(
        encoding="utf-8"
    )
    assert "friendlyError" in clip_ts
    assert "throw cause" not in clip_ts
    pub_android = ROOT / "autopilot_platform" / "frontend" / "public" / "remote" / "android" / "placeholder-mobile.svg"
    pub_ios = ROOT / "autopilot_platform" / "frontend" / "public" / "remote" / "ios" / "placeholder-mobile.svg"
    assert pub_android.is_file()
    assert pub_ios.is_file()
    ios_dispatch = (
        ROOT / "autopilot_platform" / "runner" / "remote" / "ios" / "input_dispatch.py"
    ).read_text(encoding="utf-8")
    assert 'elif t == "scroll":' in ios_dispatch


def test_device_board_has_remote_entry():
    cards = (FE / "components" / "DeviceBoardCards.vue").read_text(encoding="utf-8")
    table = (FE / "components" / "DeviceBoardTable.vue").read_text(encoding="utf-8")
    for src in (cards, table):
        assert "远程调试" in src
        assert "onOpenRemoteDevice" in src
        assert "canOpenRemote" in src


def test_can_open_remote_gate_semantics():
    """前端：占用人开控制台；管理员旁观须已有远控会话，不抢 controller。"""
    src = (FE / "composables" / "useRemoteSession.ts").read_text(encoding="utf-8")
    assert "export function canOpenRemote" in src
    assert "reservation_user_id" in src
    assert "reservation_username" in src
    assert "remote_session_active" in src
    assert "can_manage" in src
    assert 'busy_kind !== "reservation"' in src
    assert "isMobileRemotePlatform" in src
    assert "export function canObserveRemote" in src
    assert "export function prefersMjpeg" in src
    assert "pollMedia" in src
    assert "postMedia" in src
    actions = (FE / "composables" / "mcExecActions.ts").read_text(encoding="utf-8")
    assert "canObserveRemote(device, sessionUser.value)" in actions
    assert "canOpenRemote(device, sessionUser.value)" in actions
    dialog = (FE / "components" / "RemoteDeviceDialog.vue").read_text(encoding="utf-8")
    assert 'mode === "viewer"' in dialog
    assert "apiLeaveRemoteParticipant" in dialog
    assert "applyParticipantRole" in dialog
    assert "control.transferred" in dialog
    assert "participant.left" in dialog
    assert "renegotiateWebRtc(current, true)" in dialog
    assert "openedAsViewer" not in dialog
    assert "旁观中" in dialog
    assert "加入旁观会话" in dialog
    assert "handleRemoteSessionEnded" in dialog
    assert "session.closed" in dialog
    assert "isSignalingForThisPeer" in dialog
    assert "participant_role" in dialog.split("const offerBody", 1)[1].split("async function collectWebRtcStats", 1)[0]
    clipboard = (FE / "components" / "remote" / "RemoteClipboardPanel.vue").read_text(
        encoding="utf-8"
    )
    assert ':disabled="readonly || loading"' not in clipboard
    assert 'v-if="!readonly"' in clipboard
    assert "读取手机剪贴板" in clipboard
    commands = (FE / "composables" / "remote" / "useRemoteCommands.ts").read_text(encoding="utf-8")
    assert "VIEWER_READONLY_COMMANDS" in commands
    assert "file.pull" in commands


def test_remote_dialog_webrtc_and_touch_wiring():
    dialog = (FE / "components" / "RemoteDeviceDialog.vue").read_text(encoding="utf-8")
    assert "RTCPeerConnection" in dialog
    assert "xwide" in dialog
    assert " wide" not in dialog.split("<ApModal", 1)[1].split(">", 1)[0]
    # 对齐 WebAppFlaskscrcpy：浏览器不自建 input，而用 ondatachannel
    assert "ondatachannel" in dialog
    assert "client-bootstrap" in dialog
    assert 'createDataChannel("input"' not in dialog
    assert "pollTimer = null" not in dialog.split("function startTransport", 1)[1].split("function recoverWebRtcAfterTransport", 1)[0]
    assert "participant_id" in dialog.split("const offerBody", 1)[1].split("async function collectWebRtcStats", 1)[0]
    assert "resendWebRtcOfferIfNeeded" in dialog
    assert "renegotiateWebRtc" in dialog
    assert "recoverWebRtcAfterTransport" in dialog
    assert "schedulePcRecovery" in dialog
    assert "startOfferRetry" in dialog
    assert "MAX_OFFER_RETRIES" in dialog
    assert "stopOfferRetry" in dialog
    transport = (FE / "composables" / "remote" / "useRemoteTransport.ts").read_text(encoding="utf-8")
    assert "remoteWebSocketUrl" in transport
    assert "WS_READY_TIMEOUT_MS" in transport
    assert "WS_RECONNECT_BASE_MS" in transport
    assert "scheduleReconnect" in transport
    assert 'params.set("access_token"' not in transport
    bootstrap = (FE / "api" / "bootstrap.ts").read_text(encoding="utf-8")
    assert "remoteWebSocketUrl" in bootstrap
    vite = (ROOT / "autopilot_platform" / "frontend" / "vite.config.ts").read_text(encoding="utf-8")
    assert "ws: true" in vite
    channels = (ROOT / "autopilot_platform" / "runner" / "remote" / "shared" / "channels.py").read_text(
        encoding="utf-8"
    )
    assert "drain_signaling" in channels
    ws_client = (ROOT / "autopilot_platform" / "runner" / "remote" / "shared" / "ws_client.py").read_text(
        encoding="utf-8"
    )
    assert "drain_signaling" in ws_client
    assert "_SIGNALING_TYPES" in ws_client
    toolbar = (FE / "components" / "remote" / "RemoteToolbar.vue").read_text(encoding="utf-8")
    assert "电源" not in toolbar
    assert "旋转" in toolbar
    assert "方向键" in toolbar
    assert "更多" in toolbar
    assert "toggleDrawer" in toolbar
    assert "closePopovers" not in toolbar
    assert "closeMorePanel" not in toolbar
    assert "dpad-close" in toolbar
    assert "锁屏" not in toolbar
    assert "iosLock" not in toolbar
    assert "androidSwipe" in toolbar
    assert "drawerOpen" in dialog
    assert "with-drawer" in dialog
    assert "toggle-drawer" in dialog
    quick = (FE / "components" / "remote" / "RemoteQuickControls.vue").read_text(encoding="utf-8")
    assert "电源" in quick
    assert "通知栏" in quick
    assert "亮屏" in quick
    assert "展开通知" in quick
    ios_controls = (FE / "components" / "remote" / "RemoteIosControls.vue").read_text(
        encoding="utf-8"
    )
    assert "辅助触控" in ios_controls
    assert "旁白" in ios_controls
    assert "缩放" in ios_controls
    assert 't: "accessibility"' in ios_controls
    assert "alert.get" in ios_controls
    assert "input.text" in ios_controls
    assert "device.screenshot" in ios_controls
    drawer = (FE / "components" / "remote" / "RemoteSideDrawer.vue").read_text(encoding="utf-8")
    assert "RemoteQuickControls" in drawer
    assert "RemoteIosControls" in drawer
    assert "emit('close')" in drawer
    assert '["controls", "控制"]' in drawer
    assert 'id !== "controls"' not in drawer
    stage = (FE / "components" / "remote" / "RemoteStage.vue").read_text(encoding="utf-8")
    assert "handlePointerDown" in stage
    assert "props.readonly" in stage
    assert "closeRemoteSession" in dialog
    assert "teardown" in dialog
    assert "useMjpeg" in dialog
    assert "startMjpeg" in dialog
    assert "等待 WDA/MJPEG" in dialog
    assert "if (!useMjpeg.value)" in dialog.split("function startTransport", 1)[1].split(
        "async function recoverWebRtcAfterTransport", 1
    )[0]
    assert "sendIosHome" in dialog or "Home" in dialog
    assert "sendIosHardwareButton" in dialog
    assert 'dispatchRemoteCommand({' in dialog
    assert 't: "home"' in dialog
    assert "sendRemoteCommand({ t: \"home\"" not in dialog
    session_src = (
        ROOT / "autopilot_platform" / "runner" / "remote" / "ios" / "session.py"
    ).read_text(encoding="utf-8")
    assert "_submit_aux" in session_src
    assert "input_body" in session_src
    assert "command_body = command_event" in session_src
    files_panel = (FE / "components" / "remote" / "RemoteFilesPanel.vue").read_text(
        encoding="utf-8"
    )
    assert 'iosApp.value ? "/Documents"' in files_panel
    assert 'next ? "/Documents"' in files_panel
    assert "sendIosLock" not in dialog
    assert "二期" not in dialog


def test_reserve_dialog_hints_remote_after_occupy():
    src = (FE / "components" / "ReserveDeviceDialog.vue").read_text(encoding="utf-8")
    assert "远程调试" in src


def test_app_mounts_remote_dialog():
    app = (FE / "App.vue").read_text(encoding="utf-8")
    assert "RemoteDeviceDialog" in app


def test_exec_actions_open_remote():
    actions = (FE / "composables" / "mcExecActions.ts").read_text(encoding="utf-8")
    assert "export async function onOpenRemoteDevice" in actions
    assert "openRemoteDialog" in actions
    store = (FE / "stores" / "execution.ts").read_text(encoding="utf-8")
    assert "onOpenRemoteDevice" in store


def test_runner_remote_package_layout():
    remote = ROOT / "autopilot_platform" / "runner" / "remote"
    assert (remote / "hub.py").is_file()
    assert (remote / "android" / "session.py").is_file()
    android_sess = (remote / "android" / "session.py").read_text(encoding="utf-8")
    assert "_reply_media_input" in android_sess
    assert "_reply_dc_input" in android_sess
    assert "event_type.startswith(\"log.\")" in android_sess
    assert "submit_adb_dispatch" in android_sess
    assert "readonly_peer" in android_sess
    assert "readonly=readonly_peer" in android_sess
    assert 'mtype == "participant.left"' in android_sess
    peer_mgr = (remote / "android" / "webrtc" / "peer_manager.py").read_text(encoding="utf-8")
    assert "request_keyframe: bool = True" in peer_mgr
    assert "request_keyframe=not others_live" in peer_mgr
    assert (remote / "android" / "scrcpycore.py").is_file()
    assert (remote / "android" / "webrtc" / "peer_manager.py").is_file()
    assert (remote / "ios" / "session.py").is_file()
    assert (remote / "android" / "scrcpy_lifecycle.py").is_file()
    assert (remote / "ios" / "mjpeg_reader.py").is_file()
    assert (remote / "ios" / "input_dispatch.py").is_file()
    assert (remote / "shared" / "channels.py").is_file()
    assert (remote / "shared" / "protocol.py").is_file()
    assert (remote / "shared" / "coords.py").is_file()
    assert (remote / "shared" / "frame_bus.py").is_file()
    assert (remote / "shared" / "device_log_pump.py").is_file()
    pump = (remote / "shared" / "device_log_pump.py").read_text(encoding="utf-8")
    assert "post_lines" in pump
    channels = (ROOT / "autopilot_platform" / "runner" / "remote" / "shared" / "channels.py").read_text(
        encoding="utf-8"
    )
    assert "def post_device_logs" in channels
    assert "禁止混入 media/WS 画面通道" in channels
    assert 'participant_id=str(body.get("participant_id") or "")' in channels
    peer_mgr = (remote / "android" / "webrtc" / "peer_manager.py").read_text(encoding="utf-8")
    assert "async def _setup_tracks_and_channels(self, *, readonly: bool = False)" in peer_mgr
    assert "if readonly:" in peer_mgr
    ws_client = (ROOT / "autopilot_platform" / "runner" / "remote" / "shared" / "ws_client.py").read_text(
        encoding="utf-8"
    )
    assert 'item["participant_id"] = env_pid' in ws_client
    ios_sess = (remote / "ios" / "session.py").read_text(encoding="utf-8")
    assert "command_name.startswith(\"log.\")" in ios_sess
    # jar 统一在仓库根 resources/re_scrcpy/（见 runner/remote/config.py）
    jar = (
        ROOT / "resources" / "re_scrcpy" / "scrcpy-server.jar"
    )
    assert jar.is_file(), f"missing scrcpy server jar: {jar}"
    config_text = (remote / "config.py").read_text(encoding="utf-8")
    assert "4.0" in config_text
    assert "re_scrcpy" in config_text
    ios_sess = (remote / "ios" / "session.py").read_text(encoding="utf-8")
    assert "IosDevicePrep" in ios_sess
    assert "二期未就绪" not in ios_sess


def test_smoke_checklist_doc():
    smoke = DOCS / "DEVICE_REMOTE_ANDROID_SMOKE.md"
    assert smoke.is_file()
    text = smoke.read_text(encoding="utf-8")
    assert "远程调试" in text
    assert "aiortc" in text or "runner_remote" in text
    ios_smoke = DOCS / "DEVICE_REMOTE_IOS_SMOKE.md"
    assert ios_smoke.is_file()
    ios_phase = (DOCS / "DEVICE_REMOTE_IOS_PHASE2.md").read_text(encoding="utf-8")
    assert "implemented" in ios_phase.lower() or "MJPEG" in ios_phase
