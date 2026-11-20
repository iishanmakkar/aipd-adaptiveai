import { assist } from '../native/assist';
import type { ScreenTree } from '../native/assist';
import type { Settings, UserProfile } from './profile';
import { compressTree } from './agent';
import { engineChat } from './engine';

/**
 * "What is on my screen?" — the user's example flow, honestly:
 * 1) AccessibilityService reads the node tree (free, offline, instant).
 * 2) Local processing extracts texts/buttons — if the tree has enough, we answer
 *    LOCALLY with no network call at all.
 * 3) Only when the tree is empty/tiny (games, canvases, custom-drawn UIs like
 *    parts of BookMyShow/Zepto) we spend quota on a Gemini Flash vision call.
 * 4) The answer is in `spoken` so the caller can send it to TextToSpeech.
 */
export type ScreenDescription = {
  app: string;
  spoken: string;
  detail: string; // on-screen text log
  via: 'local' | 'vision' | 'empty';
  nodeCount: number;
};

export async function describeScreen(opts: {
  geminiApiKey: string;
  settings: Settings;
  profile: UserProfile;
  signal?: AbortSignal;
}): Promise<ScreenDescription> {
  let tree: ScreenTree | null = null;
  let readError = '';
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      tree = await assist.readScreen(500);
      break;
    } catch (err) {
      readError = err instanceof Error ? err.message : String(err);
      if (attempt === 2) break;
      await new Promise((r) => setTimeout(r, 1200));
      // Stop pressed during backoff: bail instead of burning two more native reads
      // and then a Gemini call that can only fail with "Stopped by the user."
      if (opts.signal?.aborted) break;
    }
  }
  if (opts.signal?.aborted) {
    return { app: '', spoken: 'Stopped.', detail: '', via: 'empty', nodeCount: 0 };
  }
  if (!tree) {
    return {
      app: '',
      spoken: `I could not read the current screen after three attempts. ${readError}`,
      detail: '',
      via: 'empty',
      nodeCount: 0,
    };
  }

  const appLabel = tree.package || 'the current app';
  const labelled = tree.nodes
    .map((n) => (n.text || n.desc || '').replace(/\s+/g, ' ').trim())
    .filter(Boolean)
    .slice(0, 14);
  const interactive = tree.nodes.filter((n) => n.click || n.editable || n.scroll).length;

  // Step 2 — local answer when the tree is rich enough. No network, no quota.
  if (tree.nodes.length >= 6 && labelled.length >= 3) {
    const head = labelled.slice(0, 8);
    const spoken =
      `You are in ${appLabel}. I can see ${tree.nodeCount} elements. ` +
      `Visible: ${head.join('. ')}. ` +
      (interactive ? `There are ${interactive} tappable items. ` : '') +
      (tree.truncated ? 'The list is long — say "read more" or ask me to find something. ' : '') +
      'Say what you want to do and I will do it.';
    return { app: appLabel, spoken, detail: compressTree(tree, 60), via: 'local', nodeCount: tree.nodeCount };
  }

  // Step 3 — tree is too thin: spend quota on Gemini vision over real pixels.
  // Honour the vision toggle: when it is off, never call Gemini with a fake image.
  if (!opts.settings.useVisionWhenAvailable) {
    const spoken =
      `You are in ${appLabel}. The screen has only ${tree.nodeCount} readable elements — ` +
      (labelled.length ? `Visible: ${labelled.join('. ')}. ` : '') +
      'Vision screenshots are off. Turn on "Use vision screenshots" in Settings so I can look at the pixels.';
    return { app: appLabel, spoken, detail: compressTree(tree, 60), via: 'empty', nodeCount: tree.nodeCount };
  }
  if (!opts.geminiApiKey) {
    const spoken =
      `You are in ${appLabel}. The screen has only ${tree.nodeCount} readable elements — ` +
      (labelled.length ? `Visible: ${labelled.join('. ')}. ` : '') +
      'This looks like a custom-drawn screen. Turn on "Use vision screenshots" in Settings and add a Gemini key so I can look at the pixels.';
    return { app: appLabel, spoken, detail: compressTree(tree, 60), via: 'empty', nodeCount: tree.nodeCount };
  }
  try {
    let base64: string | null = null;
    try {
      const st = await assist.getStatus();
      if (!st.captureActive) {
        // The caller (UI) owns the consent dialog — here we only use an active capture.
        base64 = null;
      } else {
        base64 = await assist.captureScreen(72);
      }
    } catch { base64 = null; }
    if (!base64) {
      const spoken =
        `You are in ${appLabel}. The screen has only ${tree.nodeCount} readable elements — ` +
        (labelled.length ? `Visible: ${labelled.join('. ')}. ` : '') +
        'Open the Screen tab, grant screen capture, then ask again so I can look at the pixels.';
      return { app: appLabel, spoken, detail: compressTree(tree, 60), via: 'empty', nodeCount: tree.nodeCount };
    }
    const prompt =
      'Describe this phone screen for a blind user. List the app, the visible text, buttons, and anything you can do next. ' +
      'Be honest about uncertainty. Under 80 words, speakable, no bullet points.';
    // engineChat (not chat() directly) so the model whitelist, empty-key check and
    // latency ceiling apply here exactly as they do everywhere else.
    const { text } = await engineChat({
      geminiApiKey: opts.geminiApiKey,
      settings: { ...opts.settings, temperature: 0.2 },
      messages: [
        { role: 'system', content: 'You describe phone screens for a blind user over speech.' },
        { role: 'user', content: `${prompt}\n\nAccessibility tree ${tree.nodeCount} nodes:\n${compressTree(tree, 80)}` },
      ],
      imageBase64: base64 ?? undefined,
      signal: opts.signal,
      maxTokensOverride: 2048,
      timeoutMs: 45000,
    });
    return { app: appLabel, spoken: text, detail: text, via: base64 ? 'vision' : 'local', nodeCount: tree.nodeCount };
  } catch (err) {
    const spoken =
      `You are in ${appLabel}. I can see ${tree.nodeCount} elements. ` +
      (labelled.length ? `Visible: ${labelled.join('. ')}. ` : '') +
      `Looking at the pixels failed: ${err instanceof Error ? err.message : String(err)}`;
    return { app: appLabel, spoken, detail: compressTree(tree, 60), via: 'local', nodeCount: tree.nodeCount };
  }
}

