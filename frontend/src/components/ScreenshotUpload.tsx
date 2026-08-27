import { useRef, useState, useCallback } from 'react';
import { validateImageFile } from '../utils/image';

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
        className={`upload-dropzone ${dragActive ? 'drag-active' : ''} ${displayImage ? 'has-image' : ''}`}
        htmlFor="screenshot-upload"
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
          aria-describedby="upload-hint"
        />
        
        {!displayImage ? (
          <>
            <svg className="upload-icon" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
            <span className="upload-text">Upload Screenshot</span>
            <span id="upload-hint" className="upload-hint">
              Drag & drop or click to select an image (JPG, PNG, WebP, GIF ≤ 10MB)
            </span>
          </>
        ) : (
          <div className="image-preview">
            <img src={displayImage} alt="Uploaded screenshot preview" />
            <button
              type="button"
              className="remove-image-button"
              onClick={handleRemove}
              disabled={isDescribing}
              aria-label="Remove screenshot"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
            {isDescribing && (
              <div className="describing-overlay" aria-live="polite" aria-label="Describing image">
                <div className="spinner" aria-hidden="true"></div>
                <span>Describing image…</span>
              </div>
            )}
          </div>
        )}
      </label>
      
      {error && (
        <div className="upload-error" role="alert" aria-live="assertive">
          {error}
        </div>
      )}
    </div>
  );
}