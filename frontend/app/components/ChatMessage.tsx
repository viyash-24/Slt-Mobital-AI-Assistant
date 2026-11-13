"use client";

import Image from "next/image";
import { CheckCheck, ChevronDown, Copy, FileText, RefreshCw, Share2, ThumbsDown, ThumbsUp, Verified } from "lucide-react";
import { Fragment, useState, type ReactNode } from "react";
import type { ChatMessageData } from "../types/chat";

type ChatMessageProps = {
  message: ChatMessageData;
  openSource: boolean;
  onToggleSource: () => void;
  onCopy: (text: string) => void;
};

function formatInlineText(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={index}>{part.slice(1, -1)}</code>;
    }
    return <Fragment key={index}>{part}</Fragment>;
  });
}

function FormattedResponse({ content }: { content: string }) {
  const lines = content.split(/\r?\n/);
  return <div className="response-content">
    {lines.map((line, index) => {
      const trimmedLine = line.trim();
      if (!trimmedLine) return <div className="response-spacer" key={`spacer-${index}`} />;

      const heading = trimmedLine.match(/^#{1,3}\s+(.+)$/);
      if (heading) return <h3 key={index}>{formatInlineText(heading[1])}</h3>;

      const bullet = trimmedLine.match(/^[-*]\s+(.+)$/);
      if (bullet) return <div className="response-list-item" key={index}><span className="response-bullet">•</span><span>{formatInlineText(bullet[1])}</span></div>;

      const numbered = trimmedLine.match(/^(\d+)[.)]\s+(.+)$/);
      if (numbered) return <div className="response-list-item" key={index}><span className="response-number">{numbered[1]}.</span><span>{formatInlineText(numbered[2])}</span></div>;

      return <p key={index}>{formatInlineText(trimmedLine)}</p>;
    })}
  </div>;
}

export function ChatMessage({
  message,
  openSource,
  onToggleSource,
  onCopy,
}: ChatMessageProps) {
  const [copyDone, setCopyDone] = useState(false);

  const handleCopy = () => {
    onCopy(message.content);
    setCopyDone(true);
    setTimeout(() => setCopyDone(false), 1600);
  };

  if (message.role === "user") {
    return (
      <div className="message-row user-message">
        <div>
          <div className="user-bubble">{message.content}</div>
          <div className="message-meta user-meta">
            {message.time}
            <CheckCheck size={14} />
          </div>
        </div>
      </div>
    );
  }

  const apiSources = message.sources ?? [];
  const hasSources = apiSources.length > 0;
  const sourceCount = apiSources.length;

  return (
    <div className="message-row assistant-message">
      <div className="assistant-avatar">
        <Image src="/images/emblem.svg" alt="SLT-MOBITEL" width={26} height={26} />
        <i />
      </div>
      <div className="assistant-column">
        <div className="assistant-bubble">
          <FormattedResponse content={message.content} />

          {hasSources && (
            <>
              <button className="source-toggle" onClick={onToggleSource}>
                <span>
                  <Verified size={17} />
                  {sourceCount} Verified Source{sourceCount !== 1 ? "s" : ""} from SLT-MOBITEL Knowledge Base
                </span>
                <ChevronDown size={18} className={openSource ? "rotated" : ""} />
              </button>
              {openSource && (
                <div className="source-list">
                  {apiSources.map((src, i) => (
                    <div key={i}>
                      <FileText size={16} />
                      <span>{src.title}</span>
                      <small>{src.category}</small>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>

        <div className="message-actions">
          <button aria-label="Copy response" onClick={handleCopy} title="Copy text">
            <Copy size={15} />
            {copyDone && <span style={{ fontSize: "11px", marginLeft: "4px" }}>Copied!</span>}
          </button>
          <button aria-label="Helpful response"><ThumbsUp size={15} /></button>
          <button aria-label="Not helpful"><ThumbsDown size={15} /></button>
          <button aria-label="Regenerate"><RefreshCw size={15} /></button>
          <button aria-label="Share"><Share2 size={15} /></button>
          {message.confidence && <span>Confidence: {message.confidence}</span>}
        </div>
      </div>
    </div>
  );
}