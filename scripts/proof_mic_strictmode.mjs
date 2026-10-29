// Proof for the mic fix in useVoiceRecording.ts: React 18 StrictMode's
// mount -> cleanup -> re-mount sequence, played against the exact ref logic
// of the hook, before and after the fix.
//
//   node scripts/proof_mic_strictmode.mjs

/**
 * @param resetOnMount        fix half 1: the effect resets unmountedRef on mount
 * @param releaseGuardOnBail  fix half 2: the stale-unmount bail-out releases
 *                            the re-entrancy guard
 */
const run = async ({ resetOnMount, releaseGuardOnBail }) => {
  // Refs as the hook keeps them (one instance survives the whole cycle).
  const unmountedRef = { current: false };
  const isRecordingRef = { current: false };

  // useEffect(() => { ...; return cleanup }, [])
  const mount = () => { if (resetOnMount) unmountedRef.current = false; };
  const unmount = () => { unmountedRef.current = true; }; // the hook's cleanup

  // startRecording, verbatim control flow:
  //   if (isRecordingRef.current) return;        <- re-entrancy guard
  //   isRecordingRef.current = true;
  //   const stream = await getUserMedia(...);    <- resolves; device granted
  //   if (unmountedRef.current) { stop tracks; return; }
  const startRecording = async () => {
    if (isRecordingRef.current) return { started: false, reason: 're-entrancy guard' };
    isRecordingRef.current = true;
    if (unmountedRef.current) {
      if (releaseGuardOnBail) isRecordingRef.current = false;
      return { started: false, reason: 'stale unmountedRef released the stream' };
    }
    return { started: true };
  };

  mount();
  unmount(); // StrictMode's simulated unmount
  mount();   // StrictMode's re-mount (same instance)

  const first = await startRecording();
  const second = await startRecording(); // a determined user pressing again
  return { first, second };
};

const before = await run({ resetOnMount: false, releaseGuardOnBail: false });
const after = await run({ resetOnMount: true, releaseGuardOnBail: true });

console.log('BEFORE fix — first press:', before.first, '| retry:', before.second);
console.log('AFTER  fix — first press:', after.first, '| retry:', after.second);

if (before.first.started || before.second.started) {
  console.error('PROOF FAILED: the mic was not actually dead before the fix');
  process.exit(1);
}
if (!after.first.started) {
  console.error('PROOF FAILED: the mic still does not start after the fix');
  process.exit(1);
}
console.log('PROOF OK: dead before (both presses), recording after (first press).');
