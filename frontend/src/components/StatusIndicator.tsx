interface StatusIndicatorProps {
  status: 'idle' | 'listening' | 'thinking' | 'speaking';
  listeningTime?: number;
}

export function StatusIndicator({ status, listeningTime = 0 }: StatusIndicatorProps) {
  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const getStatusContent = () => {
    switch (status) {
      case 'listening':
        return (
          <>
            <span className="status-icon listening" aria-hidden="true">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                <line x1="12" y1="19" x2="12" y2="22" />
                <line x1="8" y1="22" x2="16" y2="22" />
              </svg>
              <span className="pulse-ring"></span>
              <span className="pulse-ring"></span>
              <span className="pulse-ring"></span>
            </span>
            <span className="status-text">Listening…</span>
            {listeningTime > 0 && <span className="status-time">{formatTime(listeningTime)}</span>}
          </>
        );
      case 'thinking':
        return (
          <>
            <span className="status-icon thinking" aria-hidden="true">
              <div className="spinner" aria-hidden="true"></div>
            </span>
            <span className="status-text">Thinking…</span>
          </>
        );
      case 'speaking':
        return (
          <>
            <span className="status-icon speaking" aria-hidden="true">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <path d="M11 5L6 9H2v6h4l5 4V5z" />
                <path d="M15.54 8.46a5 5 0 0 1 0 7.07" />
                <path d="M19.07 4.93a10 10 0 0 1 0 14.14" />
              </svg>
            </span>
            <span className="status-text">Speaking…</span>
          </>
        );
      default:
        return null;
    }
  };

  const content = getStatusContent();
  if (!content) return null;

  return (
    <div 
      className={`status-indicator ${status}`} 
      role="status" 
      aria-live="polite"
      aria-atomic="true"
    >
      {content}
    </div>
  );
}