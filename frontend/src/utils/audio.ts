export function createAudioBlob(chunks: BlobPart[], mimeType = 'audio/webm;codecs=opus'): Blob {
  return new Blob(chunks, { type: mimeType });
}

export function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}