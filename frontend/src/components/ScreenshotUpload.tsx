import { useEffect, useRef, useState, useCallback } from 'react';
import { validateImageFile } from '../utils/image';
import { useDialogFocus } from '../hooks/useDialogFocus';

interface ScreenshotUploadProps {
  onImageUpload: (file: File) => Promise<void>;
  isDescribing: boolean;
  disabled?: boolean;
  currentImage?: string | null;
  onRemoveImage: () => void;
}

export function ScreenshotUpload({
  onImageUpload,
  isDescribing,
  disabled = false,
  currentImage,
  onRemoveImage,
}: ScreenshotUploadProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  // Low vision: the thumbnail is too small to see — open it fullscreen.
  const [enlarged, setEnlarged] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [inverted, setInverted] = useState(false);
  const enlargeRef = useRef<HTMLDivElement>(null);
  // aria-modal="true" promises a Tab trap and focus restored to the opener:
  // the manual focus-in effect here only half-delivered (Tab fell straight
  // out of the viewer into the page behind it, and Escape dropped focus on
  // <body>). Same hook every other dialog in the app uses.
  useDialogFocus(enlarged, enlargeRef);

  const openEnlarged = useCallback(() => {
    setZoom(1);
    setInverted(false);
    setEnlarged(true);
  }, []);

  useEffect(() => {
    if (!enlarged) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setEnlarged(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [enlarged]);

  const handleFileSelect = useCallback(async (file: File) => {
    setError(null);
    const validation = validateImageFile(file);
    
    if (!validation.valid) {
      setError(validation.error!);
      return;
    }

    setPreview(URL.createObjectURL(file));
    
    try {
      await onImageUpload(file);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to process image');
      setPreview(null);
    }
  }, [onImageUpload]);

  const handleFileInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      handleFileSelect(file);
    }
    // Reset input to allow selecting same file again
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  }, [handleFileSelect]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!disabled && !isDescribing) {
      setDragActive(true);
    }
  }, [disabled, isDescribing]);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    
    if (disabled || isDescribing) return;
    
    const file = e.dataTransfer.files[0];
    if (file && file.type.startsWith('image/')) {
      handleFileSelect(file);
    }
  }, [disabled, isDescribing, handleFileSelect]);

  const handleRemove = useCallback(() => {
    setPreview(null);
    onRemoveImage();
  }, [onRemoveImage]);

  const displayImage = preview || currentImage;

  return (
    <div className="screenshot-upload">
      <label
        className={`upload-compact ${dragActive ? 'drag-active' : ''} ${displayImage ? 'has-image' : ''}`}
        htmlFor="screenshot-upload"
        title="Attach a screenshot (drag & drop or click) — JPG, PNG, WebP, GIF, max 10MB"
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <input
          ref={fileInputRef}
          id="screenshot-upload"
          type="file"
          accept="image/jpeg,image/png,image/webp,image/gif"
          onChange={handleFileInputChange}
          disabled={disabled || isDescribing}
          className="visually-hidden"
          aria-label="Upload screenshot"
          aria-describedby="upload-hint"
        />

        {!displayImage ? (
          <>
            <svg className="upload-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
            <span className="visually-hidden">Upload screenshot</span>
          </>
        ) : (
          <button
            type="button"
            className="upload-thumb-button"
            onClick={(e) => { e.preventDefault(); e.stopPropagation(); openEnlarged(); }}
            aria-label="Enlarge screenshot preview"
            title="Enlarge"
          >
            <span className="upload-thumb" aria-hidden="true">
              <img src={displayImage} alt="" />
            </span>
          </button>
        )}
      </label>

      {enlarged && displayImage && (
        <div
          ref={enlargeRef}
          className="image-viewer-backdrop"
          role="dialog"
          aria-modal="true"
          aria-label="Enlarged screenshot"
          onClick={() => setEnlarged(false)}
        >
          <div style={{ overflow: 'auto', maxWidth: '95vw', maxHeight: '80vh' }} onClick={(e) => e.stopPropagation()}>
            <img
              className={`image-viewer-full${inverted ? ' inverted' : ''}`}
              style={{ transform: `scale(${zoom})`, transformOrigin: 'top left' }}
              src={displayImage}
              alt="Enlarged screenshot preview"
            />
          </div>
          <div className="image-viewer-toolbar" role="toolbar" aria-label="Image viewer controls" onClick={(e) => e.stopPropagation()}>
            <button type="button" onClick={() => setZoom((z) => Math.max(1, +(z - 0.5).toFixed(1)))} aria-label="Zoom out">−</button>
            <span aria-live="polite">{Math.round(zoom * 100)}%</span>
            <button type="button" onClick={() => setZoom((z) => Math.min(4, +(z + 0.5).toFixed(1)))} aria-label="Zoom in">+</button>
            <button type="button" onClick={() => setInverted((v) => !v)} aria-pressed={inverted}>
              {inverted ? 'Normal colors' : 'Invert colors'}
            </button>
          </div>
          <button
            type="button"
            className="image-viewer-close"
            onClick={() => setEnlarged(false)}
          >
            Close (Esc)
          </button>
        </div>
      )}

      {displayImage && (
        <button
          type="button"
          className="remove-image-button"
          onClick={handleRemove}
          disabled={isDescribing}
          aria-label="Remove screenshot"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>
      )}

      {isDescribing && (
        <div className="describing-overlay" role="status" aria-live="polite" aria-label="Describing image">
          <div className="spinner" aria-hidden="true"></div>
        </div>
      )}

      <span id="upload-hint" className="visually-hidden">
        Drag & drop or click to select an image (JPG, PNG, WebP, GIF, max 10MB).
        The screenshot is described aloud and used as context for your questions.
      </span>

      {error && (
        <div className="upload-error" role="alert" aria-live="assertive">
          {error}
        </div>
      )}
    </div>
  );
}