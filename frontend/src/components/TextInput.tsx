import { useRef, useEffect, useCallback } from 'react';

interface TextInputProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: (value: string) => void;
  disabled?: boolean;
  placeholder?: string;
  ariaLabel?: string;
}

export function TextInput({ 
  value, 
  onChange, 
  onSubmit, 
  disabled = false, 
  placeholder = 'Type your message...',
  ariaLabel = 'Message input'
}: TextInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const isComposingRef = useRef(false);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !isComposingRef.current) {
      e.preventDefault();
      if (value.trim() && !disabled) {
        onSubmit(value.trim());
      }
    }
  }, [value, onSubmit, disabled]);

  const handleCompositionStart = useCallback(() => {
    isComposingRef.current = true;
  }, []);

  const handleCompositionEnd = useCallback((e: React.CompositionEvent<HTMLTextAreaElement>) => {
    isComposingRef.current = false;
    onChange(e.currentTarget.value);
  }, [onChange]);

  const handleChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    if (!isComposingRef.current) {
      onChange(e.target.value);
    }
  }, [onChange]);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 150)}px`;
    }
  }, [value]);

  return (
    <div className="text-input-container">
      <textarea
        ref={textareaRef}
        value={value}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        onCompositionStart={handleCompositionStart}
        onCompositionEnd={handleCompositionEnd}
        disabled={disabled}
        placeholder={placeholder}
        aria-label={ariaLabel}
        aria-multiline="true"
        rows={1}
        className="text-input"
        spellCheck={true}
      />
      <button
        type="button"
        onClick={() => value.trim() && !disabled && onSubmit(value.trim())}
        disabled={disabled || !value.trim()}
        className="send-button"
        aria-label="Send message"
        aria-disabled={disabled || !value.trim()}
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path d="M22 2L11 13" />
          <path d="M22 2L15 22L11 13L2 9L22 2Z" />
        </svg>
      </button>
    </div>
  );
}