import { useEffect, useRef, useState } from 'react';
import { useDialogFocus } from '../hooks/useDialogFocus';
import { useVoiceRecording } from '../hooks/useVoiceRecording';
import { useSpeechToText } from '../hooks/useSpeechToText';
import { MicButton } from './MicButton';
import { apiService } from '../services/api';
import { describeApiError } from '../utils/apiError';
import type { FormFillResult, PageField } from '../types/api';

export interface FillableForm {
  url: string;
  fields: PageField[];
}

interface FormFillDialogProps {
  page: FillableForm;
  onClose: () => void;
  /** Spoken through the chat's TTS so the result reaches a blind user
   * without them having to find this dialog's live region. */
  // Returns 'spoken' | 'silent' so the caller COULD tell whether the user heard
  // anything; this dialog never claims that they did, so it discards the result.
  announce?: (text: string) => Promise<unknown>;
}

/** Real form filling through POST /api/form-fill: the backend's live Chromium
 * discovers the fields, caches them, fills, and — on replay — heals broken
 * selectors. Values the user types here are sent as-is; nothing is mocked. */
export function FormFillDialog({ page, onClose, announce }: FormFillDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  useDialogFocus(true, dialogRef);
  // Keyed by index+label: two fields can share a label, and keying the state
  // by label alone let one input overwrite the other's value. The payload
  // sent to the backend stays label-keyed (that is what it matches on).
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<FormFillResult | null>(null);
  // Which field voice dictation targets: the last focused input, else the
  // first empty one. Without this every transcript would need a label match.
  const [focusedIndex, setFocusedIndex] = useState(0);
  const busyRef = useRef(busy);
  busyRef.current = busy;
  const recordingRef = useRef(false);
  const stateRef = useRef({ values, focusedIndex, fields: page.fields });
  stateRef.current = { values, focusedIndex, fields: page.fields };
  const runRef = useRef<(replay: boolean) => Promise<void>>(async () => {});
  // The 30s recording cap auto-stops inside the hook: without a delivery
  // path here the dictated value was dropped on the floor (the same bug
  // ChatInterface already fixed for its mic — "a 30s hold lost everything").
  // Release/mic-button stops still flow through handleDictateStop below.
  const dictateStopRef = useRef<(blob: Blob) => void>(() => {});
  const { isRecording, recordingTime, startRecording, stopRecording, cancelRecording, error: recError } =
    useVoiceRecording({
      onAutoStop: (blob) => dictateStopRef.current(blob),
      // A dictation that dies with this dialog is a discarded form value:
      // parking it handed it to the chat's draft-recovery pipeline, which
      // transcribed it and submitted it as a chat message on the next load.
      persistOnUnmount: false,
    });
  recordingRef.current = isRecording;
  const { transcribe, isTranscribing } = useSpeechToText();

  const dictateInto = (text: string) => {
    const typed = text.match(/^\s*type\s+(.+)$/i)?.[1]?.trim() ?? text.trim();
    if (!typed) return;
    const { values: cur, focusedIndex: focusIdx, fields } = stateRef.current;
    // Focused field first (what the user just heard announced), else the
    // first empty field, else append to the focused one.
    const focusedKey = `${focusIdx}:${fields[focusIdx]?.label ?? ''}`;
    let idx = focusIdx;
    if ((cur[focusedKey] ?? '').trim()) {
      const empty = fields.findIndex((f, i) => !((cur[`${i}:${f.label}`] ?? '').trim()));
      idx = empty >= 0 ? empty : focusIdx;
    }
    const field = fields[idx];
    if (!field) return;
    const key = `${idx}:${field.label}`;
    setValues((prev) => ({ ...prev, [key]: ((prev[key] ?? '') ? `${prev[key]} ` : '') + typed }));
    setFocusedIndex(idx);
    void announce?.(`${field.label} set to ${typed}.`);
  };

  // A second form loaded while the dialog is open is a NEW dialog: stale
  // values, results and errors must not carry over (or be sent to the wrong
  // page), and the new form gets announced.
  useEffect(() => {
    setValues({});
    setResult(null);
    setError('');
  }, [page.url]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Escape while filling would unmount mid-POST and lose the result;
      // Close stays enabled too, symmetrically. Escape while DICTATING must
      // also stay put: MicButton's discard handler registers when recording
      // starts — strictly AFTER this dialog's listener — so window listeners
      // fire in registration order and this one ran FIRST, closing the
      // dialog (and destroying every typed value) instead of discarding the
      // recording. The dictation is discarded by MicButton; the dialog lives.
      if (e.key === 'Escape' && !busy && !recordingRef.current) onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose, busy]);

  // Blindfolded-critical: opening this dialog silently leaves the user with
  // no idea what happened or what to type where. Announce the dialog and
  // speak each field's label as it takes focus.
  useEffect(() => {
    void announce?.(
      `Form fill dialog opened for the live page. ${page.fields.length} fields found. ` +
      'Type a value for each field as it is announced; leave a field blank to skip it. ' +
      'Then press the Fill the form button.',
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run on open + page switch
  }, [page.url]);

  const valueKey = (index: number, label: string) => `${index}:${label}`;
  const setValue = (key: string, value: string) =>
    setValues((prev) => ({ ...prev, [key]: value }));

  const payloadValues = (): Record<string, string> => {
    const payload: Record<string, string> = {};
    page.fields.forEach((field, index) => {
      const value = (values[valueKey(index, field.label)] ?? '').trim();
      if (value && !(field.label in payload)) payload[field.label] = value;
    });
    return payload;
  };

  const run = async (replay: boolean) => {
    const pv = payloadValues();
    if (!replay) {
      const missing = page.fields.filter((f, i) => f.required && !(values[valueKey(i, f.label)] ?? '').trim());
      if (missing.length) {
        const msg = `Please fill required: ${missing.map((f) => f.label).join(', ')}.`;
        setError(msg);
        void announce?.(msg);
        return;
      }
      if (!Object.keys(pv).length) {
        const msg = 'Type a value for at least one field before filling.';
        setError(msg);
        void announce?.(msg);
        return;
      }
    }
    setBusy(true);
    setError('');
    try {
      const filled = await apiService.formFill(page.url, pv, replay);
      setResult(filled);
      const summary =
        `Form fill ${filled.status}: ${filled.success_count} succeeded` +
        `${filled.failure_count ? `, ${filled.failure_count} failed` : ''}` +
        (filled.unfilled?.length ? `. Not filled: ${filled.unfilled.join(', ')}` : '') +
        (filled.page_message ? `. The page says: ${filled.page_message}` : '') +
        (filled.healed?.status === 'repaired' ? '. Broken fields were re-found and repaired.' : '');
      void announce?.(summary);
    } catch (err) {
      const msg = describeApiError(err);
      setError(msg);
      void announce?.(msg);
    } finally {
      setBusy(false);
    }
  };

  runRef.current = run;

  // Voice control: chat dispatches dictation + submit when the dialog is the
  // active fill surface, so a blind user never leaves the voice flow.
  useEffect(() => {
    const onDictation = (e: Event) => {
      dictateInto((e as CustomEvent<{ text: string }>).detail?.text ?? '');
    };
    const onSubmit = () => { if (!busyRef.current) void runRef.current(false); };
    window.addEventListener('adaptiveai:dialog-dictation', onDictation);
    window.addEventListener('adaptiveai:fill-submit', onSubmit);
    return () => {
      window.removeEventListener('adaptiveai:dialog-dictation', onDictation);
      window.removeEventListener('adaptiveai:fill-submit', onSubmit);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- stable listeners, refs for latest
  }, [page.url]);

  const handleDictateStop = async (autoBlob?: Blob) => {
    const blob = autoBlob ?? await stopRecording();
    if (!blob) return;
    try {
      const transcript = await transcribe(blob);
      dictateInto(transcript);
    } catch {
      const msg = 'Dictation failed. Please try again or type the value.';
      setError(msg);
      void announce?.(msg);
    }
  };
  dictateStopRef.current = (blob) => void handleDictateStop(blob);

  const repaired = result?.healed?.status === 'repaired';

  return (
    <div ref={dialogRef} role="dialog" aria-modal="true" aria-label="Fill this form" className="command-palette form-fill-dialog">
      <h2>Fill this form</h2>
      <p className="form-fill-url">{page.url}</p>
      <p>Type or dictate a value for each field below. Anything left blank is skipped. Say “type” before words to enter them literally.</p>

      {page.fields.map((field, index) => {
        // Labels contain spaces/brackets — raw interpolation produced invalid
        // HTML ids, breaking label→input association (and the accessible name)
        // for exactly the screen-reader users this dialog serves.
        const inputId = `form-fill-${index}`;
        const key = valueKey(index, field.label);
        const currentValue = values[key] ?? '';
        const isPassword = /password|passcode|otp|code/i.test(field.label) || field.type === 'password';
        const dup = page.fields.findIndex((f) => f.label === field.label) !== index;
        return (
          <div key={`${field.label}-${index}`} className="form-fill-field">
            <label htmlFor={inputId}>
              {/* page-context labels often already carry "(required)" — never double it */}
              {field.label}{field.required && !/\(required\)/i.test(field.label) ? ' (required)' : ''} — {field.type}
              {dup ? ' (note: same label twice — first value is sent)' : ''}
            </label>
            <input
              id={inputId}
              type={isPassword ? 'password' : 'text'}
              value={currentValue}
              onChange={(e) => setValue(key, e.target.value)}
              onFocus={() => {
                setFocusedIndex(index);
                void announce?.(
                  `${field.label}. ${field.required ? 'Required. ' : 'Optional. '}` +
                  (isPassword ? 'Hidden field.' : `${currentValue ? 'Current value set.' : 'Empty.'}`),
                );
              }}
              autoComplete={isPassword ? 'new-password' : 'off'}
            />
          </div>
        );
      })}

      <div className="form-fill-actions">
        <MicButton
          onStartRecording={() => startRecording()}
          onStopRecording={() => void handleDictateStop()}
          onCancelRecording={cancelRecording}
          isRecording={isRecording}
          recordingTime={recordingTime}
          disabled={busy || isTranscribing}
          error={recError}
        />
        <span className="form-fill-hint" aria-hidden="true">
          {isRecording ? 'Dictating… release to fill the focused field' : isTranscribing ? 'Writing down what you said…' : 'Hold to dictate a value'}
        </span>
      </div>

      <div className="form-fill-actions">
        <button type="button" onClick={() => void run(false)} disabled={busy}>
          {busy ? 'Filling…' : 'Fill the form'}
        </button>
        <button type="button" onClick={() => void run(true)} disabled={busy || !result}>
          Replay last fill (auto-heal)
        </button>
        <button type="button" onClick={onClose} disabled={busy}>
          Close
        </button>
      </div>

      {error && <p className="alt-format-error" role="alert">{error}</p>}

      {result && (
        <div className="form-fill-result" role="status" aria-live="polite">
          <p>
            Status: {result.status} — {result.success_count} field{result.success_count === 1 ? '' : 's'} filled,
            {' '}{result.failure_count} failed.
          </p>
          {result.page_message && <p>The page says: {result.page_message}</p>}
          {result.unfilled && result.unfilled.length > 0 && (
            <p>Not filled: {result.unfilled.join(', ')}.</p>
          )}
          {repaired && (
            <p>
              Healed: {result.healed?.repaired_fields} broken selector
              {result.healed?.repaired_fields === 1 ? '' : 's'} re-found
              {result.healed?.repairs?.length
                ? ` (${result.healed.repairs.map((r) => r.label).join(', ')})`
                : ''}.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
