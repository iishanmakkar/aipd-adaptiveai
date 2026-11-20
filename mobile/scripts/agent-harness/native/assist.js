// Simulated Android device for host-testing the real agent loop.
// Mirrors the AdaptiveAssist bridge surface exactly; no React Native involved.

const SCREEN_FORM = 'form';
const SCREEN_RESULTS = 'results';

let screen = SCREEN_FORM;
const filled = {};
const log = [];

function formNodes() {
  return [
    { id: 1, d: 1, cls: 'TextView', text: 'Book Train Tickets', b: [40, 120, 700, 180], cx: 370, cy: 150 },
    { id: 2, d: 2, cls: 'EditText', text: '', desc: 'From Station', res: 'com.railyatri:id/et_from', b: [40, 220, 700, 300], cx: 370, cy: 260, editable: true, click: true },
    { id: 3, d: 2, cls: 'EditText', text: '', desc: 'To Station', res: 'com.railyatri:id/et_to', b: [40, 320, 700, 400], cx: 370, cy: 360, editable: true, click: true },
    { id: 4, d: 2, cls: 'EditText', text: '', desc: 'Journey Date', res: 'com.railyatri:id/et_date', b: [40, 420, 700, 500], cx: 370, cy: 460, editable: true, click: true },
    { id: 5, d: 2, cls: 'EditText', text: '', desc: 'Passengers', res: 'com.railyatri:id/et_pax', b: [40, 520, 700, 600], cx: 370, cy: 560, editable: true, click: true },
    { id: 6, d: 2, cls: 'EditText', text: '', desc: 'Email for ticket', res: 'com.railyatri:id/et_email', b: [40, 620, 700, 700], cx: 370, cy: 660, editable: true, click: true },
    { id: 7, d: 2, cls: 'Button', text: 'Search Trains', res: 'com.railyatri:id/btn_search', b: [40, 740, 700, 830], cx: 370, cy: 785, click: true },
  ];
}

function resultNodes() {
  return [
    { id: 1, d: 1, cls: 'TextView', text: '3 trains found Delhi to Mumbai', b: [40, 120, 700, 180], cx: 370, cy: 150 },
    { id: 2, d: 2, cls: 'TextView', text: '12951 Mumbai Rajdhani 16:55 - 08:35 3A INR 2450', b: [40, 220, 700, 320], cx: 370, cy: 270, click: true },
    { id: 3, d: 2, cls: 'TextView', text: '12137 Punjab Mail 21:40 - 19:05 SL INR 640', b: [40, 340, 700, 440], cx: 370, cy: 390, click: true },
    { id: 4, d: 2, cls: 'Button', text: 'Book Now', res: 'com.railyatri:id/btn_book', b: [40, 740, 700, 830], cx: 370, cy: 785, click: true },
  ];
}

function nodes() {
  return screen === SCREEN_FORM ? formNodes() : resultNodes();
}

const assist = {
  async getStatus() {
    return {
      accessibilityEnabled: true,
      sttAvailable: true,
      onDeviceStt: true,
      listening: false,
      captureActive: false,
      foregroundApp: 'com.railyatri',
      sdkInt: 36,
    };
  },
  async readScreen() {
    const list = nodes().map((n) => ({
      ...n,
      text: filled[n.id] !== undefined ? filled[n.id] : n.text,
    }));
    return { package: 'com.railyatri', nodeCount: list.length, truncated: false, nodes: list };
  },
  async findByText(query) {
    const q = String(query).toLowerCase();
    return nodes()
      .filter((n) => `${n.text || ''} ${n.desc || ''}`.toLowerCase().includes(q))
      .map((n) => ({
        id: n.id, text: n.text || '', desc: n.desc || '', cls: n.cls, res: n.res || null,
        cx: n.cx, cy: n.cy, editable: Boolean(n.editable), click: Boolean(n.click),
      }));
  },
  async fillNode(id, value) {
    const node = nodes().find((n) => n.id === id);
    if (!node || !node.editable) return { ok: false, text: '' };
    filled[id] = value;
    log.push(`fill(#${id} ${node.desc || node.text}) = "${value}"`);
    return { ok: true, text: value };
  },
  async clickNode(id) {
    const node = nodes().find((n) => n.id === id);
    if (!node) return false;
    log.push(`click(#${id} ${node.text || node.desc})`);
    if (node.res === 'com.railyatri:id/btn_search') {
      // The fake app refuses to search until the mandatory fields are filled.
      const missing = [2, 3, 4].filter((k) => !filled[k]);
      if (missing.length) return false;
      screen = SCREEN_RESULTS;
    }
    return true;
  },
  async tap(x, y) { log.push(`tap(${x},${y})`); return true; },
  async longPress(x, y) { log.push(`longPress(${x},${y})`); return true; },
  async swipe() { log.push('swipe'); return true; },
  async scrollNode() { return true; },
  async globalAction(a) { log.push(`global(${a})`); return true; },
  async launchApp(p) { log.push(`launch(${p})`); return true; },
  async openUrl(u) { log.push(`openUrl(${u})`); return true; },
  async listApps() { return [{ package: 'com.railyatri', label: 'RailYatri' }]; },
  async requestScreenCapture() { return true; },
  async captureScreen() { return null; },
  async stopScreenCapture() { return true; },
  async speak(t) { log.push(`speak("${t}")`); return 'u1'; },
  async startVoice() { return true; },
  async stopVoice() { return true; },
};

module.exports = {
  assist,
  assistAvailable: true,
  subscribeVoice: () => () => {},
  ensureMicPermission: async () => true,
  ensureNotificationPermission: async () => true,
  __state: () => ({ screen, filled, log }),
  __reset: () => { screen = SCREEN_FORM; for (const k of Object.keys(filled)) delete filled[k]; log.length = 0; },
};
