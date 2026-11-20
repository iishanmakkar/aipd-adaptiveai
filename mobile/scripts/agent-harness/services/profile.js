// Minimal stub of src/services/profile.ts — the agent only calls noteTaskPhrase at runtime.
const phrases = [];
module.exports = {
  noteTaskPhrase: (p) => phrases.push(p),
  __phrases: phrases,
};
