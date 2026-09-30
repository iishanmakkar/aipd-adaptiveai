/** Phase 4.4 — Sign-language avatar (ASL fingerspelling starter).
 * Lightweight, no Three.js dependency: spells key terms letter-by-letter
 * in a dedicated panel. A full HamNoSys/SiGML avatar can replace this
 * component behind the same props.
 */
export function SignAvatar({ text, maxLetters = 12 }: { text: string; maxLetters?: number }) {
  const letters = text
    .toUpperCase()
    .replace(/[^A-Z]/g, '')
    .slice(0, maxLetters)
    .split('');
  if (letters.length === 0) return null;
  return (
    <div className="sign-avatar" role="img" aria-label={`Fingerspelling: ${letters.join(' ')}`}>
      <span className="sign-caption">ASL fingerspelling</span>
      <div className="sign-letters" aria-hidden="true">
        {letters.map((ch, i) => (
          <span key={i} className="sign-letter" title={ch}>
            {ch}
          </span>
        ))}
      </div>
    </div>
  );
}
