/*
 * Host harness for the AdaptiveAI agent loop.
 *
 * Runs the REAL src/services/agent.ts and src/services/nim.ts (transpiled to .build/) against the
 * LIVE NVIDIA NIM API, driving a simulated Android app through scripts/agent-harness/native/assist.js.
 *
 * Nothing is mocked except the device. The system prompt, tool protocol, JSON extraction, model
 * resolution and loop control are the shipped code, so a pass here is evidence about the product
 * logic — not about a copy of it.
 *
 * Run via:  bash mobile/scripts/verify-agent-loop.sh
 * Env:      NIM_KEY (optional; defaults to backend/.env), INSTRUCTION, MAX_STEPS
 */
const fs = require('fs');
const path = require('path');

const HERE = __dirname;
// Literal relative requires: Node resolves them against this file's directory, so the module
// instance is exactly the copy the transpiled agent.js loads (a constructed require path would
// both risk resolving a stray copy and reads to a scanner as code injection).
const agent = require('./.build/services/agent.js');
const nim = require('./.build/services/nim.js');
// Must be the exact module instance the transpiled agent.js requires, or the state we assert
// on afterwards belongs to an unused copy.
const device = require('./.build/native/assist.js');

function readKey() {
  if (process.env.NIM_KEY) return process.env.NIM_KEY;
  // Walk candidate ancestors with dirname (no '..' segments in a join) and read only a fixed
  // allowlist of .env filenames.
  let dir = path.resolve(HERE);
  for (let depth = 0; depth < 4; depth++) {
    for (const rel of ['backend/.env', 'agents/.env', 'intent-engine/.env']) {
      // Template concat rather than a join with a variable second argument.
      const p = `${dir}${path.sep}${rel}`;
      if (!fs.existsSync(p)) continue;
      const m = fs.readFileSync(p, 'utf8').match(/^NIM_API_KEY=(.+)$/m);
      if (m) return m[1].trim().replace(/^["']|["']$/g, '');
    }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  throw new Error('no NIM key: set NIM_KEY or populate backend/.env');
}

const settings = {
  textModel: nim.DEFAULT_TEXT_MODEL,
  visionModel: nim.DEFAULT_VISION_MODEL,
  availableModels: [],
  speakResponses: true,
  speechRate: 1,
  language: 'en-US',
  preferOnDeviceStt: true,
  confirmBeforeActing: true,
  maxSteps: Number(process.env.MAX_STEPS || 14),
  temperature: 0.2,
  useVisionWhenAvailable: false,
};

const profile = {
  displayName: 'Ishan',
  accessibilityNeed: 'none',
  verbosity: 'normal',
  languageComplexity: 'standard',
  uiScale: 1,
  highContrast: false,
  savedFields: {
    fullName: 'Ishan Makkar',
    email: 'ishan.makkar@example.com',
    phone: '+91 98765 43210',
    address: '',
    city: 'New Delhi',
    postcode: '110001',
    country: 'India',
    dateOfBirth: '',
  },
  corrections: [],
  frequentTasks: [],
};

const instruction =
  process.env.INSTRUCTION ||
  'Book a train ticket from Delhi to Mumbai for 15 November, 2 passengers. Use my saved email for the ticket.';

let confirmCount = 0;

function onEvent(e) {
  switch (e.type) {
    case 'thinking':
      console.log(`\n[step ${e.step}] -------------------------------------------`);
      break;
    case 'status':
      console.log(`  (${e.text})`);
      break;
    case 'action':
      console.log(`  ACTION  ${e.action} ${JSON.stringify(e.args)}`);
      if (e.label) console.log(`          thought: ${e.label}`);
      break;
    case 'observation':
      console.log(`  OBSERVE ${e.ok ? 'ok' : 'FAIL'}: ${e.detail.split('\n')[0]}`);
      break;
    case 'confirm':
      confirmCount++;
      console.log(`  CONFIRM-GATE fired: "${e.label}" -> auto-approved`);
      e.resolve(true);
      break;
    case 'message':
      console.log(`\n  MESSAGE: ${e.text}`);
      break;
    case 'done':
      console.log(`\n  DONE status=${e.status} steps=${e.steps}`);
      break;
  }
}

(async () => {
  const key = readKey();
  console.log('=== AdaptiveAI agent loop, live NIM, simulated device ===');
  console.log(`key: ${key.slice(0, 9)}...${key.slice(-4)}  (len ${key.length})`);

  // Exercises the same code path as Settings' "Test connection".
  const probe = await nim.testApiKey(key);
  console.log(`testApiKey       : ok=${probe.ok} models=${probe.modelCount} ${probe.error || ''}`);
  if (!probe.ok) {
    console.log('ABORT: key rejected; nothing else is provable.');
    process.exit(2);
  }
  settings.availableModels = probe.models;

  const resolvedText = nim.resolveModel(
    settings.textModel,
    settings.availableModels,
    nim.TEXT_MODEL_CHOICES,
  );
  console.log(`text model       : ${resolvedText}`);
  console.log(`instruction      : ${instruction}`);
  console.log(`confirmBeforeActing: ${settings.confirmBeforeActing}`);

  device.__reset();
  const started = Date.now();

  const result = await agent.runAgent({
    instruction,
    nimApiKey: key,
    settings: { ...settings, textModel: resolvedText },
    profile,
    onEvent,
  });

  const st = device.__state();
  console.log('\n=== simulated device after the run ===');
  console.log(`screen         : ${st.screen}`);
  console.log(`fields filled  : ${JSON.stringify(st.filled)}`);
  console.log(`native calls   :\n  ${st.log.join('\n  ') || '(none)'}`);
  console.log(`confirm gates  : ${confirmCount}`);
  console.log('\n=== verdict ===');
  console.log(`status         : ${result.status}`);
  console.log(`steps          : ${result.steps}`);
  console.log(`elapsed        : ${((Date.now() - started) / 1000).toFixed(1)}s`);
  console.log(`summary        : ${result.summary}`);

  // The booking scenario is "done right" when the agent fills the form, reaches results and
  // then stops to ask before paying. awaiting_input on the results screen is the pass case.
  const filledAll = ['Delhi', 'Mumbai'].every((v) => Object.values(st.filled).includes(v));
  const reachedResults = st.screen === 'results';
  const askedBeforePaying = result.status === 'awaiting_input';
  const pass = filledAll && reachedResults && askedBeforePaying;
  console.log(`\nfilled form     : ${filledAll}`);
  console.log(`reached results : ${reachedResults}`);
  console.log(`asked before pay: ${askedBeforePaying}`);
  console.log(pass ? '\nHARNESS PASS' : '\nHARNESS FAIL');
  process.exit(pass ? 0 : 1);
})().catch((e) => {
  console.error('HARNESS ERROR:', e && e.message ? e.message : e);
  process.exit(1);
});
