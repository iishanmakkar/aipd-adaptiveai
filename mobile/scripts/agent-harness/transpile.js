// Transpiles the shipped TS sources the harness exercises into .build/ as CommonJS.
// The chain is the real one: agent.ts -> engine.ts -> localLlm.ts -> (react-native shim),
// plus nim.ts. No product code is rewritten — Node just gets a tiny react-native stub so
// the same modules that run on the phone run here.
const path = require('path');
const fs = require('fs');

// Plain specifier: Node's resolution walks up from this file and finds the app's pinned
// TypeScript in mobile/node_modules — no constructed require path.
const ts = require('typescript');
const root = path.resolve(__dirname, '..', '..');
const build = path.join(__dirname, '.build', 'services');
fs.mkdirSync(build, { recursive: true });

for (const [src, out] of [
  ['src/services/nim.ts', 'nim.js'],
  ['src/services/agent.ts', 'agent.js'],
  ['src/services/engine.ts', 'engine.js'],
  ['src/services/localLlm.ts', 'localLlm.js'],
]) {
  const code = fs.readFileSync(path.join(root, src), 'utf8');
  const result = ts.transpileModule(code, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      esModuleInterop: true,
    },
  });
  fs.writeFileSync(path.join(build, out), result.outputText);
}

// The transpiled agent.js requires '../native/assist' relative to its own directory, so the
// device stub must sit at .build/native/assist.js. The profile stub provides the one runtime
// call agent.ts makes (none currently — profile types are erased) and keeps older builds of
// run.js working.
fs.mkdirSync(path.join(build, '..', 'native'), { recursive: true });
fs.copyFileSync(
  path.join(__dirname, 'native', 'assist.js'),
  path.join(build, '..', 'native', 'assist.js'),
);
fs.copyFileSync(path.join(__dirname, 'services', 'profile.js'), path.join(build, 'profile.js'));

// react-native stub for localLlm.js: no native AdaptiveLocalLlm module in Node, so
// localLlmAvailable() is false and getLoaded() returns null — the harness runs the NIM path.
// It lives in .build/node_modules so Node resolves it ahead of the real react-native
// package in the repo root's node_modules.
const shimDir = path.join(build, '..', 'node_modules', 'react-native');
fs.mkdirSync(shimDir, { recursive: true });
fs.writeFileSync(
  path.join(shimDir, 'package.json'),
  JSON.stringify({ name: 'react-native', main: 'index.js' }),
);
fs.writeFileSync(
  path.join(shimDir, 'index.js'),
  [
    '// Minimal stand-in for react-native inside the agent harness.',
    'const noop = () => () => {};',
    'module.exports = {',
    '  NativeModules: {},',
    '  NativeEventEmitter: class { addListener() { return { remove: noop }; } removeListeners() {} },',
    '  Platform: { OS: "node", Version: 0, select: (o) => o.node ?? o.default },',
    '};',
    '',
  ].join('\n'),
);

console.log('transpiled nim/agent/engine/localLlm ->', build);
