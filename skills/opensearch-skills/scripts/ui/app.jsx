const { useEffect, useState, useRef, useCallback } = React;

const TEMPLATES = [
  { id: "document", label: "Document" },
  { id: "ecommerce", label: "E-Commerce" },
  { id: "agent", label: "Agent" },
];

const AGENT_PROMPTS_FALLBACK = {
  search: [
    "Find items with high ratings from recent years",
    "Show me entries in a specific category",
    "Top results matching a keyword",
    "Items with particular attributes or filters",
  ],
  chat: [
    "What are the highest rated items?",
    "Tell me about the most popular categories",
    "Recommend something interesting",
    "Which items stand out in this collection?",
  ],
};

function TemplateIcon({ id }) {
  const size = 20;
  if (id === "document") {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/>
      </svg>
    );
  }
  if (id === "ecommerce") {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/>
      </svg>
    );
  }
  if (id === "agent") {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
      </svg>
    );
  }
  return null;
}

// ---------------------------------------------------------------------------
// Field role inference for ecommerce/media templates
// ---------------------------------------------------------------------------
const TITLE_HINTS = ["title", "name", "label", "heading", "subject", "primarytitle"];
const IMAGE_HINTS = ["image", "img", "poster", "photo", "thumbnail", "picture", "cover", "avatar", "logo"];
const DESC_HINTS = ["description", "summary", "overview", "abstract", "content", "body", "text", "plot"];
const NOT_TITLE_HINTS = ["titletype", "type", "category", "kind"];

function inferFieldRoles(source, schema, fieldOverrides) {
  const roles = { title: null, image: null, description: null, tags: [], metrics: [] };
  if (!source) return roles;

  // Apply user overrides first
  if (fieldOverrides) {
    if (fieldOverrides.title && fieldOverrides.title !== "(none)" && source[fieldOverrides.title] != null) {
      roles.title = { field: fieldOverrides.title, value: String(source[fieldOverrides.title]) };
    }
    if (fieldOverrides.description && fieldOverrides.description !== "(none)" && source[fieldOverrides.description] != null) {
      roles.description = { field: fieldOverrides.description, value: String(source[fieldOverrides.description]) };
    }
    if (fieldOverrides.image && fieldOverrides.image !== "(none)" && source[fieldOverrides.image] != null) {
      roles.image = { field: fieldOverrides.image, value: String(source[fieldOverrides.image]) };
    }
  }

  const fieldCategories = schema?.field_categories || {};
  const keywordFields = new Set(fieldCategories.keyword || []);
  const numericFields = new Set(fieldCategories.numeric || []);

  for (const [key, val] of Object.entries(source)) {
    if (val == null || typeof val === "object") continue;
    const lower = key.toLowerCase();
    const strVal = String(val);

    if (!roles.title && TITLE_HINTS.some((h) => lower.includes(h)) && !NOT_TITLE_HINTS.some((h) => lower === h) && strVal.length < 200) {
      roles.title = { field: key, value: strVal };
      continue;
    }
    if (!roles.image && (IMAGE_HINTS.some((h) => lower.includes(h)) || /^https?:\/\/.+\.(jpe?g|png|gif|webp|svg)/i.test(strVal))) {
      roles.image = { field: key, value: strVal };
      continue;
    }
    if (!roles.description && DESC_HINTS.some((h) => lower.includes(h)) && strVal.length > 20) {
      roles.description = { field: key, value: strVal };
      continue;
    }
    if (keywordFields.has(key) && strVal.length < 60) {
      roles.tags.push({ field: key, value: strVal });
    } else if (numericFields.has(key)) {
      roles.metrics.push({ field: key, value: val });
    }
  }

  // Fallback: use first short text as title, first long text as description
  if (!roles.title || !roles.description) {
    for (const [key, val] of Object.entries(source)) {
      if (val == null || typeof val === "object") continue;
      const strVal = String(val);
      if (!roles.title && strVal.length >= 3 && strVal.length < 120 && /[a-zA-Z]/.test(strVal)) {
        roles.title = { field: key, value: strVal };
      } else if (!roles.description && strVal.length > 40 && !/^https?:\/\//.test(strVal)) {
        roles.description = { field: key, value: strVal.slice(0, 300) };
      }
      if (roles.title && roles.description) break;
    }
  }

  return roles;
}

// ---------------------------------------------------------------------------
// Template: Ecommerce (grid cards with images, tags, metrics)
// ---------------------------------------------------------------------------
function EcommerceResults({ results, loading, schema, fieldOverrides, filterSource }) {
  if (loading) return null;
  return (
    <div className="ecommerce-grid">
      {results.map((item, idx) => {
        const displaySource = filterSource ? filterSource(item.source) : item.source;
        const roles = inferFieldRoles(displaySource, schema, fieldOverrides);
        return (
          <article className="ecommerce-card" key={item.id || idx} style={{ animationDelay: `${idx * 40}ms` }}>
            {roles.image && (
              <div className="ecommerce-image">
                <img src={roles.image.value} alt="" loading="lazy" onError={(e) => { e.target.style.display = "none"; }} />
              </div>
            )}
            <div className="ecommerce-body">
              <div className="ecommerce-title-row">
                <span className="ecommerce-rank">{idx + 1}</span>
                <span className="ecommerce-title">{roles.title?.value || item.preview || item.id}</span>
              </div>
              {roles.description && roles.description.value !== (roles.title?.value || "") && (
                <div className="ecommerce-desc">{roles.description.value}</div>
              )}
              {roles.tags.length > 0 && (
                <div className="ecommerce-tags">
                  {roles.tags.slice(0, 5).map((tag) => (
                    <span key={tag.field} className="ecommerce-tag" title={tag.field}>{tag.value}</span>
                  ))}
                </div>
              )}
              <div className="ecommerce-footer">
                {roles.metrics.slice(0, 3).map((m) => (
                  <span key={m.field} className="ecommerce-metric" title={m.field}>
                    {m.field}: <strong>{m.value}</strong>
                  </span>
                ))}
                <span className="score">score {Number(item.score || 0).toFixed(3)}</span>
              </div>
            </div>
          </article>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Template: Document Search (list with large previews, score bars)
// ---------------------------------------------------------------------------
function DocumentResults({ results, loading, filterSource, schema, fieldOverrides }) {
  if (loading) return null;
  return (
    <div className="results doc-results">
      {results.map((item, idx) => {
        const s = item.source || {};
        const displaySource = filterSource ? filterSource(s) : s;
        const roles = inferFieldRoles(displaySource, schema, fieldOverrides);
        const title = roles.title?.value || item.preview || "Untitled";
        const metaParts = [];
        roles.tags.slice(0, 3).forEach((tag) => metaParts.push(tag.value));
        roles.metrics.slice(0, 2).forEach((m) => metaParts.push(`${m.field}: ${m.value}`));
        const metaLine = metaParts.join(" · ");
        const score = Number(item.score || 0).toFixed(4);
        return (
          <article className="doc-card" key={item.id || idx} style={{ animationDelay: `${idx * 35}ms` }}>
            <span className="doc-rank">{idx + 1}</span>
            <div className="doc-content">
              <div className="doc-title">{title}</div>
              {metaLine && <div className="doc-meta">{metaLine}</div>}
              <div className="doc-details-row">
                <details className="doc-details">
                <summary>View details</summary>
                <div className="doc-details-content">
                  <div className="doc-detail-row"><span className="doc-detail-label">ID:</span> <code>{item.id || "(none)"}</code></div>
                  <pre>{JSON.stringify(displaySource, null, 2)}</pre>
                </div>
              </details>
              <span className="doc-score-inline">{score}</span>
              </div>
            </div>
          </article>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Template: Agentic Chat
// ---------------------------------------------------------------------------
// Generate a conversational summary from search results
function generateChatSummary(query, results, total, schema) {
  if (!results || results.length === 0) {
    return `I couldn't find any results matching "${query}". Try rephrasing your question or using different keywords.`;
  }

  const count = total ?? results.length;
  const topItems = results.slice(0, 5);

  let summary = `I found ${count} result${count !== 1 ? "s" : ""} for your query. `;

  if (count <= 3) {
    summary += `Here's what I found:\n\n`;
  } else {
    summary += `Here are the top matches:\n\n`;
  }

  topItems.forEach((item, i) => {
    const s = item.source || {};
    const roles = inferFieldRoles(s, schema, null);
    const title = roles.title?.value || item.preview || "Untitled";
    const score = Number(item.score || 0);
    const tags = roles.tags.slice(0, 2).map((t) => t.value).join(", ");
    const tagsStr = tags ? ` ${"\u2022"} ${tags}` : "";

    summary += `${i + 1}. **${title}**`;
    summary += `${tagsStr}`;
    if (score > 0) summary += ` ${"\u2022"} Relevance: ${score.toFixed(2)}`;
    summary += `\n`;
    if (roles.description && roles.description.value !== title) {
      const shortDesc = roles.description.value.length > 150 ? roles.description.value.slice(0, 147) + "..." : roles.description.value;
      summary += `   ${shortDesc}\n`;
    }
    summary += `\n`;
  });

  if (count > 5) {
    summary += `...and ${count - 5} more result${count - 5 !== 1 ? "s" : ""}.`;
  }

  return summary;
}

// Simple markdown-like rendering (bold only)
function renderChatText(text) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    return part;
  });
}

function AgenticChat({ messages, loading, onPromptClick, agentPrompts, agentPromptsLoaded, schema }) {
  const endRef = useRef(null);
  useEffect(() => {
    if (messages.length > 0) endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  return (
    <div className="chat-messages">
      {messages.length === 0 && (
        <div className="chat-empty">
          <div className="chat-empty-icon">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" style={{opacity: 0.3}}>
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
            </svg>
          </div>
          <div className="chat-empty-title">Conversational Search</div>
          <div className="chat-empty-desc">Ask follow-up questions and the agent will remember the context of your conversation.</div>
          <div className="suggested-prompts">
            {(agentPrompts?.chat?.length > 0 ? agentPrompts.chat : (agentPromptsLoaded ? AGENT_PROMPTS_FALLBACK.chat : [])).map((p) => (
              <button key={p} className="suggested-prompt" onClick={() => onPromptClick && onPromptClick(p)}>{p}</button>
            ))}
          </div>
        </div>
      )}
      {messages.map((msg, idx) => (
        <div key={idx} className={`chat-bubble chat-${msg.role}`}>
          {msg.role === "user" ? (
            <div className="chat-user-text">{msg.text}</div>
          ) : (
            <div className="chat-assistant">
              {msg.results && msg.results.length > 0 ? (
                <>
                  {msg.agent_steps_summary && (
                    <details className="chat-agent-reasoning" open>
                      <summary>Agent reasoning</summary>
                      <div className="chat-reasoning-content">
                        <div className="chat-reasoning-section">
                          <div className="chat-reasoning-label">Steps</div>
                          <pre className="chat-reasoning-pre">{msg.agent_steps_summary}</pre>
                        </div>
                      </div>
                    </details>
                  )}
                  <div className="chat-summary">
                    {renderChatText(msg.summary || generateChatSummary(msg.query, msg.results, msg.total, schema))}
                  </div>
                  <div className="chat-meta-bar">
                    <span>{msg.total ?? msg.results.length} result(s) {"\u2022"} {msg.took_ms ?? 0}ms</span>
                    {msg.capability && <span className="chat-cap-badge">{msg.capability}</span>}
                  </div>
                  <details className="chat-sources">
                    <summary>View source documents ({msg.results.length})</summary>
                    <div className="chat-source-list">
                      {msg.results.slice(0, 10).map((item, i) => (
                        <div key={i} className="chat-source-item">
                          <span className="chat-source-num">{i + 1}</span>
                          <div className="chat-source-body">
                            <div className="chat-source-title">{item.source?.title || item.source?.name || item.preview || item.id}</div>
                            <pre>{JSON.stringify(item.source, null, 2)}</pre>
                          </div>
                        </div>
                      ))}
                    </div>
                  </details>
                  {msg.dsl_query && (
                    <details className="chat-agent-reasoning">
                      <summary>Generated DSL</summary>
                      <div className="chat-reasoning-content">
                        <div className="chat-reasoning-section">
                          <pre className="chat-reasoning-pre">{(() => { try { return JSON.stringify(JSON.parse(msg.dsl_query), null, 2); } catch(e) { return msg.dsl_query; } })()}</pre>
                        </div>
                      </div>
                    </details>
                  )}
                </>
              ) : msg.error ? (
                <div className="chat-error">{msg.error}</div>
              ) : (
                <div className="chat-summary">I couldn't find any results for that query. Try rephrasing your question.</div>
              )}
            </div>
          )}
        </div>
      ))}
      {loading && (
        <div className="chat-bubble chat-assistant">
          <div className="chat-typing">
            <span className="chat-typing-dot"></span>
            <span className="chat-typing-dot"></span>
            <span className="chat-typing-dot"></span>
          </div>
        </div>
      )}
      <div ref={endRef} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Custom Dropdown for version/index selection
// ---------------------------------------------------------------------------
function IndexDropdown({ value, options, onChange, placeholder }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const handleClick = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const selected = options.find((o) => o.name === value);

  return (
    <div className="idx-dropdown" ref={ref}>
      <button className="idx-dropdown-trigger" onClick={() => setOpen(!open)} type="button">
        <span className="idx-dropdown-value">{selected ? selected.name : (placeholder || "Select...")}</span>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M6 9l6 6 6-6"/>
        </svg>
      </button>
      {open && (
        <div className="idx-dropdown-menu">
          {options.map((opt) => (
            <button
              key={opt.name}
              className={`idx-dropdown-item ${opt.name === value ? "selected" : ""}`}
              onClick={() => { onChange(opt.name); setOpen(false); }}
              type="button"
            >
              <div className="idx-dropdown-item-name">{opt.name}</div>
              <div className="idx-dropdown-item-meta">{opt.description || `${opt.docs} docs`}</div>
              <div className="idx-dropdown-item-meta">{[opt.created, opt.docs ? `${opt.docs} docs` : ""].filter(Boolean).join(" · ")}</div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// View Mode Selector (List / Compare)
// ---------------------------------------------------------------------------
function ViewModeSelector({ enabled, onToggle }) {
  return (
    <div className="view-mode-seg" role="radiogroup" aria-label="View mode">
      <button
        className={`view-mode-btn ${!enabled ? "active" : ""}`}
        onClick={() => onToggle(false)}
        role="radio"
        aria-checked={!enabled}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/>
        </svg>
        Single
      </button>
      <button
        className={`view-mode-btn ${enabled ? "active" : ""}`}
        onClick={() => onToggle(true)}
        role="radio"
        aria-checked={enabled}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="3" width="7" height="18" rx="1"/><rect x="14" y="3" width="7" height="18" rx="1"/>
        </svg>
        Compare
      </button>
    </div>
  );
}


// ---------------------------------------------------------------------------
// ResultPane – one half of the comparison view
// ---------------------------------------------------------------------------
function ResultPane({ label, indexName, results, loading, error, stats, queryMode, capability, usedSemantic, fallbackReason, activeTemplate, schema, fieldOverrides, filterSource }) {
  const capabilityDesc = {
    exact: "Lexical BM25",
    semantic: "Semantic Vector",
    structured: "Structured Filter",
    combined: "Hybrid BM25 + Dense Vector",
    autocomplete: "Autocomplete",
    fuzzy: "Fuzzy Match",
    manual: "Manual Query",
  };

  const desc = capability ? (capabilityDesc[capability] || capability) : "";

  return (
    <div className="result-pane">
      <div className="result-pane-header">
        <span className="result-pane-name">{indexName || label}</span>
        {desc && <span className="result-pane-desc">{desc}</span>}
        <span className="result-pane-stats">{stats}</span>
      </div>

      {loading && (
        <div className="result-pane-loading">
          <div className="loading-bar"><div className="loading-bar-progress"></div></div>
          <span className="loading-text">Searching...</span>
        </div>
      )}

      {error && <div className="result-pane-error">{error}</div>}

      {!loading && !error && (
        <div className="result-pane-results">
          {activeTemplate === "ecommerce" || activeTemplate === "media" ? (
            <EcommerceResults results={results} loading={false} schema={schema} fieldOverrides={fieldOverrides} filterSource={filterSource} />
          ) : (
            <DocumentResults results={results} loading={false} filterSource={filterSource} schema={schema} fieldOverrides={fieldOverrides} />
          )}
        </div>
      )}
    </div>
  );
}


// ---------------------------------------------------------------------------
// Comparison View — side-by-side search across two selected indices
// ---------------------------------------------------------------------------
function ComparisonView({ query, searchSize, activeTemplate, schema, fieldOverrides, filterSource, compareIndex1, compareIndex2 }) {
  // Index 1 pane state
  const [index1Results, setIndex1Results] = useState([]);
  const [index1Loading, setIndex1Loading] = useState(false);
  const [index1Error, setIndex1Error] = useState("");
  const [index1Stats, setIndex1Stats] = useState("Ready");
  const [index1QueryMode, setIndex1QueryMode] = useState("");
  const [index1Capability, setIndex1Capability] = useState("");
  const [index1UsedSemantic, setIndex1UsedSemantic] = useState(false);
  const [index1FallbackReason, setIndex1FallbackReason] = useState("");

  // Index 2 pane state
  const [index2Results, setIndex2Results] = useState([]);
  const [index2Loading, setIndex2Loading] = useState(false);
  const [index2Error, setIndex2Error] = useState("");
  const [index2Stats, setIndex2Stats] = useState("Ready");
  const [index2QueryMode, setIndex2QueryMode] = useState("");
  const [index2Capability, setIndex2Capability] = useState("");
  const [index2UsedSemantic, setIndex2UsedSemantic] = useState(false);
  const [index2FallbackReason, setIndex2FallbackReason] = useState("");

  const runComparisonSearch = async (queryText) => {
    setIndex1Loading(true);
    setIndex2Loading(true);
    setIndex1Error("");
    setIndex2Error("");

    const makeRequest = (indexName) => {
      const qs = new URLSearchParams();
      qs.set("index", indexName);
      qs.set("q", queryText);
      qs.set("size", String(searchSize));
      qs.set("debug", "1");
      return fetch(`/api/search?${qs.toString()}`).then(r => r.json());
    };

    const [result1, result2] = await Promise.allSettled([
      makeRequest(compareIndex1),
      makeRequest(compareIndex2),
    ]);

    // Handle index 1 result
    if (result1.status === "fulfilled") {
      const data = result1.value;
      if (data.error) {
        setIndex1Error(data.error);
        setIndex1Results([]);
      } else {
        setIndex1Results(data.hits || []);
        setIndex1Stats(`${data.total ?? 0} hits — ${data.took_ms ?? 0}ms`);
        setIndex1QueryMode(data.query_mode || "");
        setIndex1Capability(data.capability || "");
        setIndex1UsedSemantic(Boolean(data.used_semantic));
        setIndex1FallbackReason(data.fallback_reason || "");
      }
    } else {
      setIndex1Error(result1.reason?.message || "Request failed");
      setIndex1Results([]);
    }
    setIndex1Loading(false);

    // Handle index 2 result
    if (result2.status === "fulfilled") {
      const data = result2.value;
      if (data.error) {
        setIndex2Error(data.error);
        setIndex2Results([]);
      } else {
        setIndex2Results(data.hits || []);
        setIndex2Stats(`${data.total ?? 0} hits — ${data.took_ms ?? 0}ms`);
        setIndex2QueryMode(data.query_mode || "");
        setIndex2Capability(data.capability || "");
        setIndex2UsedSemantic(Boolean(data.used_semantic));
        setIndex2FallbackReason(data.fallback_reason || "");
      }
    } else {
      setIndex2Error(result2.reason?.message || "Request failed");
      setIndex2Results([]);
    }
    setIndex2Loading(false);
  };

  // Trigger search when query or searchSize changes
  useEffect(() => {
    if (query && query.trim()) {
      runComparisonSearch(query.trim());
    }
  }, [query, searchSize]);

  return (
    <div>
      {/* Side-by-side result panes */}
      <div className="comparison-panes">
        <ResultPane
          label="Index 1"
          indexName={compareIndex1}
          results={index1Results}
          loading={index1Loading}
          error={index1Error}
          stats={index1Stats}
          queryMode={index1QueryMode}
          capability={index1Capability}
          usedSemantic={index1UsedSemantic}
          fallbackReason={index1FallbackReason}
          activeTemplate={activeTemplate}
          schema={schema}
          fieldOverrides={fieldOverrides}
          filterSource={filterSource}
        />
        <ResultPane
          label="Index 2"
          indexName={compareIndex2}
          results={index2Results}
          loading={index2Loading}
          error={index2Error}
          stats={index2Stats}
          queryMode={index2QueryMode}
          capability={index2Capability}
          usedSemantic={index2UsedSemantic}
          fallbackReason={index2FallbackReason}
          activeTemplate={activeTemplate}
          schema={schema}
          fieldOverrides={fieldOverrides}
          filterSource={filterSource}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main App
// ---------------------------------------------------------------------------
function App() {
  const [indexName, setIndexName] = useState("");
  const [searchSize, setSearchSize] = useState("20");
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [stats, setStats] = useState("Ready");
  const [queryMode, setQueryMode] = useState("");
  const [capability, setCapability] = useState("");
  const [fallbackReason, setFallbackReason] = useState("");
  const [usedSemantic, setUsedSemantic] = useState(false);
  const [autocompleteField, setAutocompleteField] = useState("");
  const [autocompleteOptions, setAutocompleteOptions] = useState([]);
  const [backendType, setBackendType] = useState("");
  const [backendEndpoint, setBackendEndpoint] = useState("");
  const [backendConnected, setBackendConnected] = useState(false);

  // Comparison mode state
  const [comparisonAvailable, setComparisonAvailable] = useState(false);
  const [comparisonEnabled, setComparisonEnabled] = useState(false);
  const [compareIndex1, setCompareIndex1] = useState("");
  const [compareIndex2, setCompareIndex2] = useState("");
  const [availableIndices, setAvailableIndices] = useState([]);

  // Template & settings state
  const [schema, setSchema] = useState(null);
  const [activeTemplate, setActiveTemplate] = useState("document");
  const [showSettings, setShowSettings] = useState(false);
  const [darkMode, setDarkMode] = useState(false);

  // Chat / agent state
  const [chatMessages, setChatMessages] = useState([]);
  const [memoryId, setMemoryId] = useState(null);
  const [prevComparisonEnabled, setPrevComparisonEnabled] = useState(false);
  const [ragAnswer, setRagAnswer] = useState("");
  const [agentStepsSummary, setAgentStepsSummary] = useState("");
  const [dslQuery, setDslQuery] = useState("");
  // "search" = google-like (flow agent), "chat" = chatbox (conversational agent)
  const [agenticMode, setAgenticMode] = useState("search");
  const [agentPrompts, setAgentPrompts] = useState({ search: [], chat: [] });
  const [agentPromptsLoaded, setAgentPromptsLoaded] = useState(false);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", darkMode);
  }, [darkMode]);

  // Field mapping overrides
  const [titleField, setTitleField] = useState("(none)");
  const [descField, setDescField] = useState("(none)");
  const [imgField, setImgField] = useState("(none)");
  const [hiddenFields, setHiddenFields] = useState(new Set());

  const fieldOverrides = {
    title: titleField !== "(none)" ? titleField : null,
    description: descField !== "(none)" ? descField : null,
    image: imgField !== "(none)" ? imgField : null,
  };

  const toggleHiddenField = (field) => {
    setHiddenFields((prev) => {
      const next = new Set(prev);
      if (next.has(field)) next.delete(field);
      else next.add(field);
      return next;
    });
  };

  const filterSource = (source) => {
    if (!source || hiddenFields.size === 0) return source;
    const out = {};
    for (const [k, v] of Object.entries(source)) {
      if (!hiddenFields.has(k)) out[k] = v;
    }
    return out;
  };

  const capabilityLabel = {
    exact: "Exact",
    semantic: "Semantic",
    structured: "Structured",
    combined: "Combined",
    autocomplete: "Autocomplete",
    fuzzy: "Fuzzy",
    manual: "Manual",
  };

  // ---- Template change with comparison mode management ----
  const handleTemplateChange = (newTemplate) => {
    if (newTemplate === "agent" && activeTemplate !== "agent") {
      setPrevComparisonEnabled(comparisonEnabled);
      setComparisonEnabled(false);
    } else if (newTemplate !== "agent" && activeTemplate === "agent") {
      setComparisonEnabled(prevComparisonEnabled);
    }
    setActiveTemplate(newTemplate);
  };

  // ---- Schema fetch ----
  const schemaLoadedRef = useRef(false);
  const fetchSchema = useCallback(async (index) => {
    if (!index) return;
    try {
      const res = await fetch(`/api/schema?index=${encodeURIComponent(index)}`);
      const data = await res.json();
      if (!data.error) {
        setSchema(data);
        // Always update agentic mode when agent type changes
        if (data.agentic_agent_type) {
          setAgenticMode(data.agentic_agent_type === "conversational" ? "chat" : "search");
        }
        if (!schemaLoadedRef.current) {
          schemaLoadedRef.current = true;
          const suggested = data.suggested_template || "document";
          setActiveTemplate(suggested);
          if (suggested === "agent") {
            setComparisonEnabled(false);
          }
          if (data.agentic_agent_type) {
            loadAgentPrompts(index);
          }
        }
      }
    } catch (_) {}
  }, []);

  // ---- Agent Prompts ----
  const loadAgentPrompts = async (index) => {
    if (!index) return;
    setAgentPromptsLoaded(false);
    // Race: API response vs 5s timeout for fallback
    const fallbackTimer = setTimeout(() => {
      setAgentPromptsLoaded(true);
    }, 5000);
    try {
      const res = await fetch(`/api/agent-prompts?index=${encodeURIComponent(index)}`);
      const data = await res.json();
      clearTimeout(fallbackTimer);
      if ((data.search && data.search.length > 0) || (data.chat && data.chat.length > 0)) {
        setAgentPrompts(data);
      }
      setAgentPromptsLoaded(true);
    } catch (_) {
      clearTimeout(fallbackTimer);
      setAgentPromptsLoaded(true);
    }
  };

  // ---- Suggestions ----
  const loadSuggestions = async (index) => {
    try {
      const qs = new URLSearchParams();
      if (index) qs.set("index", index);
      const res = await fetch(`/api/suggestions?${qs.toString()}`);
      const data = await res.json();
      const raw = Array.isArray(data.suggestions) ? data.suggestions : [];
      const mapped = raw
        .map((entry) => ({
          text: String(entry.text || "").trim(),
          capability: String(entry.capability || "").trim().toLowerCase(),
          query_mode: String(entry.query_mode || "default").trim(),
          field: String(entry.field || "").trim(),
          value: String(entry.value || "").trim(),
          case_insensitive: Boolean(entry.case_insensitive),
        }))
        .filter((entry) => entry.text.length > 0 && entry.capability.length > 0);
      setSuggestions(mapped);
    } catch (_) { setSuggestions([]); }
  };

  // ---- Config ----
  const loadConfig = async () => {
    try {
      const res = await fetch("/api/config");
      const data = await res.json();
      setBackendType(String(data.backend_type || "").trim());
      setBackendEndpoint(String(data.endpoint || "").trim());
      setBackendConnected(Boolean(data.connected));
      const defaultIndex = (data.default_index || "").trim();
      if (defaultIndex) {
        setIndexName(defaultIndex);
        await loadSuggestions(defaultIndex);
        await fetchSchema(defaultIndex);
        return;
      }
      await loadSuggestions("");
    } catch (_err) {
      await loadSuggestions("");
    }
  };

  const loadComparisonConfig = async () => {
    try {
      const res = await fetch("/api/comparison-config");
      const data = await res.json();
      if (data.comparison_enabled) {
        setComparisonAvailable(true);
        setComparisonEnabled(true);
        setCompareIndex1(data.baseline_index);
        setCompareIndex2(data.improved_index);
        // Use index 2 for suggestions and schema in comparison mode
        await loadSuggestions(data.improved_index);
        await fetchSchema(data.improved_index);
      }
    } catch (err) {
      console.error("Failed to fetch comparison config:", err);
    }
  };

  const loadIndices = async () => {
    try {
      const res = await fetch("/api/indices");
      const data = await res.json();
      const list = Array.isArray(data.indices) ? data.indices : [];
      setAvailableIndices(list);
      if (list.length >= 2) setComparisonAvailable(true);
    } catch (_) {}
  };

  useEffect(() => { loadConfig(); loadComparisonConfig(); loadIndices(); }, []);

  // Refetch schema when index changes (debounced)
  useEffect(() => {
    const idx = indexName.trim();
    if (!idx) return;
    const timer = setTimeout(() => fetchSchema(idx), 400);
    return () => clearTimeout(timer);
  }, [indexName, fetchSchema]);

  // ---- Autocomplete ----
  useEffect(() => {
    const effectiveIndex = (comparisonEnabled && compareIndex2) ? compareIndex2 : indexName.trim();
    const prefix = query.trim();
    const autocompleteActive = effectiveIndex.length > 0 && prefix.length >= 2;

    if (!autocompleteActive) {
      setAutocompleteOptions([]);
      return;
    }

    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const qs = new URLSearchParams();
        qs.set("index", effectiveIndex);
        qs.set("q", prefix);
        qs.set("size", "8");
        if (autocompleteField) {
          qs.set("field", autocompleteField);
        }
        const res = await fetch(`/api/autocomplete?${qs.toString()}`);
        const data = await res.json();
        const resolvedField = String(data.field || "").trim();
        const options = Array.isArray(data.options)
          ? data.options
              .map((value) => String(value || "").trim())
              .filter((value) => value.length > 0)
          : [];
        if (!cancelled) {
          if (resolvedField) {
            setAutocompleteField((prev) => (prev === resolvedField ? prev : resolvedField));
          }
          setAutocompleteOptions(options);
        }
      } catch (_err) {
        if (!cancelled) {
          setAutocompleteOptions([]);
        }
      }
    }, 120);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [indexName, query, capability, queryMode, autocompleteField, comparisonEnabled, compareIndex2]);

  // ---- Agent Search ----
  const runAgentSearch = async (overrideQuery = null) => {
    const effectiveQuery = (overrideQuery !== null ? overrideQuery : query).trim();
    const effectiveIndex = indexName.trim();
    if (!effectiveIndex || !effectiveQuery) return;

    setChatMessages(prev => [...prev, { role: "user", text: effectiveQuery }]);
    setLoading(true);
    setError("");

    try {
      const qs = new URLSearchParams();
      qs.set("index", effectiveIndex);
      qs.set("q", effectiveQuery);
      qs.set("size", String(parseInt(searchSize, 10) || 20));
      qs.set("debug", "1");
      if (memoryId) qs.set("memory_id", memoryId);

      const res = await fetch(`/api/search?${qs.toString()}`);
      const data = await res.json();

      if (data.error) {
        const friendlyError = data.error.includes("expired") 
          ? "AI agent credentials have expired. Please refresh and try again."
          : data.error.includes("timeout") 
          ? "The AI agent took too long to respond. Please try a simpler question."
          : "I had trouble processing your question. Please try rephrasing it.";
        setChatMessages(prev => [...prev, { role: "assistant", error: friendlyError }]);
      } else {
        const hits = Array.isArray(data.hits) ? data.hits : [];
        const summary = generateChatSummary(effectiveQuery, hits, data.total ?? 0, schema);
        setChatMessages(prev => [...prev, {
          role: "assistant",
          query: effectiveQuery,
          results: hits,
          total: data.total ?? 0,
          took_ms: data.took_ms ?? 0,
          capability: data.capability || "",
          summary: data.rag_answer || summary,
          agent_steps_summary: data.agent_steps_summary || "",
          dsl_query: data.dsl_query || "",
        }]);
        if (data.memory_id) setMemoryId(data.memory_id);
      }
    } catch (err) {
      setChatMessages(prev => [...prev, { role: "assistant", error: "Something went wrong. Please try again." }]);
    } finally {
      setLoading(false);
      setQuery("");
    }
  };

  // ---- Search ----
  const runSearch = async (overrideQuery = null, options = {}) => {
    if (activeTemplate === "agent" && agenticMode === "chat") { runAgentSearch(overrideQuery); return; }
    // In comparison mode, ComparisonView handles search via its own useEffect on query
    if (comparisonEnabled) return;
    const effectiveQuery = (overrideQuery !== null ? overrideQuery : query).trim();
    const effectiveIndex = indexName.trim();
    const effectiveSize = parseInt(searchSize, 10) || 20;
    if (!effectiveIndex) { setError("Please enter an index name."); return; }

    setError("");
    setLoading(true);

    try {
      const qs = new URLSearchParams();
      qs.set("index", effectiveIndex);
      qs.set("q", effectiveQuery);
      qs.set("size", String(effectiveSize));
      qs.set("debug", "1");
      if (options.intent) qs.set("intent", options.intent);
      if (options.field) qs.set("field", options.field);
      const res = await fetch(`/api/search?${qs.toString()}`);
      const data = await res.json();

      if (data.error) {
        setError(data.error);
        setResults([]);
        setStats("Search failed");
        setQueryMode(""); setCapability(""); setFallbackReason(""); setUsedSemantic(false);
      } else {
        const hits = Array.isArray(data.hits) ? data.hits : [];
        setResults(hits);
        setStats(`Loaded ${data.total ?? 0} hit(s) in ${data.took_ms ?? 0} ms`);
        setQueryMode(String(data.query_mode || ""));
        setCapability(String(data.capability || ""));
        setFallbackReason(String(data.fallback_reason || ""));
        setUsedSemantic(Boolean(data.used_semantic));
        setRagAnswer(String(data.rag_answer || ""));
        setAgentStepsSummary(String(data.agent_steps_summary || ""));
        setDslQuery(String(data.dsl_query || ""));
        await loadSuggestions(effectiveIndex);
      }
    } catch (err) {
      setError(`Request failed: ${err.message}`);
      setResults([]);
      setStats("Search failed");
      setQueryMode(""); setCapability(""); setFallbackReason(""); setUsedSemantic(false);
    } finally {
      setLoading(false);
    }
  };

  const onSuggestionClick = (entry) => {
    const text = String(entry?.text || "").trim();
    if (!text) return;
    setAutocompleteField(String(entry?.capability || "").toLowerCase() === "autocomplete" ? String(entry?.field || "") : "");
    setAutocompleteOptions([]);
    setQuery(text);
    runSearch(text);
  };

  const onAutocompleteOptionClick = (value) => {
    const text = String(value || "").trim();
    if (!text) return;
    setAutocompleteOptions([]);
    setQuery(text);
    runSearch(text, { intent: "autocomplete_selection", field: autocompleteField });
  };

  // Derive field lists from schema for field mapping dropdowns
  const allFields = schema?.field_specs ? Object.keys(schema.field_specs).filter((f) => !f.endsWith(".keyword")) : [];
  const textFields = (schema?.field_categories?.text || []);

  return (
    <div className={`shell template-${activeTemplate}`}>
      <header className="topbar">
        <div className="brand">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 42.6667 42.6667" fill="none" aria-label="OpenSearch" role="img">
            <path className="logo-light" fill="#075985" d="M41.1583 15.6667C40.3252 15.6667 39.6499 16.342 39.6499 17.1751C39.6499 29.5876 29.5876 39.6499 17.1751 39.6499C16.342 39.6499 15.6667 40.3252 15.6667 41.1583C15.6667 41.9913 16.342 42.6667 17.1751 42.6667C31.2537 42.6667 42.6667 31.2537 42.6667 17.1751C42.6667 16.342 41.9913 15.6667 41.1583 15.6667Z"/>
            <path className="logo-dark" fill="#082F49" d="M32.0543 25.3333C33.5048 22.967 34.9077 19.8119 34.6317 15.3947C34.06 6.24484 25.7726 -0.696419 17.9471 0.0558224C14.8835 0.350311 11.7379 2.84747 12.0173 7.32032C12.1388 9.26409 13.0902 10.4113 14.6363 11.2933C16.1079 12.1328 17.9985 12.6646 20.1418 13.2674C22.7308 13.9956 25.7339 14.8135 28.042 16.5144C30.8084 18.553 32.6994 20.9162 32.0543 25.3333Z"/>
            <path className="logo-light" fill="#075985" d="M2.6124 9.33333C1.16184 11.6997 -0.241004 14.8548 0.0349954 19.2719C0.606714 28.4218 8.89407 35.3631 16.7196 34.6108C19.7831 34.3164 22.9288 31.8192 22.6493 27.3463C22.5279 25.4026 21.5765 24.2554 20.0304 23.3734C18.5588 22.5339 16.6681 22.0021 14.5248 21.3992C11.9358 20.6711 8.93276 19.8532 6.62463 18.1522C3.85831 16.1136 1.96728 13.7505 2.6124 9.33333Z"/>
          </svg>
          OpenSearch
        </div>
        <div className="divider"></div>
        <div className="title">Launchpad</div>
        <div className="topbar-right">
          <div className={`conn-badge ${backendConnected ? "connected" : "disconnected"}`}>
            <span className="conn-dot"></span>
            <strong>{backendConnected ? "Connected" : "Disconnected"}</strong>
            {backendEndpoint && <span className="conn-ep">{backendEndpoint}</span>}
          </div>
          <button className={`hdr-btn ${showSettings ? "on" : ""}`} onClick={() => setShowSettings(!showSettings)}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
            </svg>
            <span>Settings</span>
          </button>
        </div>
      </header>

      {showSettings && (
        <div className="settings-panel">
          {/* Index / Size / View mode row */}
          <div className="idx-row">
            {availableIndices.length >= 2 && activeTemplate !== "agent" && (
              <div className="field-group">
                <label>View</label>
                <ViewModeSelector
                enabled={comparisonEnabled}
                onToggle={(on) => {
                  if (on) {
                    setComparisonEnabled(true);
                    if (!compareIndex1 || !compareIndex2) {
                      const current = indexName.trim();
                      const names = availableIndices.map((i) => i.name);
                      const other = names.find((n) => n !== current) || "";
                      if (!compareIndex1) setCompareIndex1(current || names[0] || "");
                      if (!compareIndex2) setCompareIndex2(other || names[1] || "");
                    }
                  } else {
                    setComparisonEnabled(false);
                    if (compareIndex1) {
                      setIndexName(compareIndex1);
                    }
                  }
                }}
              />
              </div>
            )}
            <div className="field-group">
              <label>Index</label>
              {availableIndices.length > 0 ? (
                <IndexDropdown
                  value={comparisonEnabled ? compareIndex1 : indexName}
                  options={comparisonEnabled ? availableIndices.filter((i) => i.name !== compareIndex2) : availableIndices}
                  onChange={(v) => {
                    if (comparisonEnabled) {
                      setCompareIndex1(v);
                    } else {
                      setIndexName(v);
                      loadSuggestions(v);
                      fetchSchema(v);
                      setChatMessages([]);
                      setMemoryId(null);
                    }
                  }}
                  placeholder="Select index..."
                />
              ) : (
                <input className="idx-input" value={indexName} onChange={(e) => setIndexName(e.target.value)} placeholder="e.g. my-index" />
              )}
            </div>
            {comparisonEnabled && (
              <>
              <span className="vs-label">vs</span>
              <div className="field-group">
                <label>Index 2</label>
                <IndexDropdown
                  value={compareIndex2}
                  options={availableIndices.filter((i) => i.name !== compareIndex1)}
                  onChange={(v) => { setCompareIndex2(v); loadSuggestions(v); fetchSchema(v); }}
                  placeholder="Select..."
                />
              </div>
              </>
            )}
            <div className="field-group">
              <label>Size</label>
              <input className="size-input" value={searchSize} onChange={(e) => setSearchSize(e.target.value)} />
            </div>
            <div className="spacer"></div>
            <div className="field-group">
              <label>Theme</label>
              <div className="theme-seg">
                <button
                  className={`theme-seg-btn ${!darkMode ? "active" : ""}`}
                  onClick={() => setDarkMode(false)}
                  aria-label="Light mode"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
                  </svg>
                </button>
                <button
                  className={`theme-seg-btn ${darkMode ? "active" : ""}`}
                  onClick={() => setDarkMode(true)}
                  aria-label="Dark mode"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
                  </svg>
                </button>
              </div>
            </div>
          </div>

          <div className="settings-section">
          <div className="sec-label">Template</div>
          <div className="tpl-grid">
            {TEMPLATES.map((t) => {
              const disabled = !!t.disabled;
              const isAgent = t.id === "agent";
              const isActive = activeTemplate === t.id;
              return (
                <div key={t.id} className={`tpl-card-wrap ${isAgent && isActive ? "expanded" : ""}`}>
                  <button
                    className={`tpl-card ${isActive ? "on" : ""} ${disabled ? "disabled" : ""}`}
                    disabled={disabled}
                    title=""
                    onClick={() => {
                      if (disabled) return;
                      handleTemplateChange(t.id);
                    }}
                  >
                    <div className="tpl-card-icon"><TemplateIcon id={t.id} /></div>
                    <div className="tpl-card-label">{t.label}</div>
                    {schema?.suggested_template === t.id && <span className="template-auto">auto</span>}
                  </button>
                  {isAgent && isActive && (
                    <div className="agent-mode-sub">
                      <button
                        className={`agent-mode-opt ${agenticMode === "search" ? "active" : ""} ${schema?.agentic_agent_type === "conversational" ? "disabled" : ""}`}
                        onClick={(e) => { e.stopPropagation(); if (schema?.agentic_agent_type !== "conversational") setAgenticMode("search"); }}
                        title={schema?.agentic_agent_type === "conversational" ? "Search requires a flow agent" : ""}
                      >
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                        Search
                        <span className="agent-mode-opt-desc">Answer + results</span>
                      </button>
                      <button
                        className={`agent-mode-opt ${agenticMode === "chat" ? "active" : ""} ${schema?.agentic_agent_type === "flow" ? "disabled" : ""}`}
                        onClick={(e) => { e.stopPropagation(); if (schema?.agentic_agent_type !== "flow") setAgenticMode("chat"); }}
                        title={schema?.agentic_agent_type === "flow" ? "Chat requires a conversational agent" : ""}
                      >
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                        Chat
                        <span className="agent-mode-opt-desc">Conversational</span>
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          </div>

          <div className="settings-section">
          {/* Field mapping */}
          <div className="field-map-row">
            <div className="field-map-group">
              <label>Title</label>
              <select value={titleField} onChange={(e) => setTitleField(e.target.value)}>
                <option>(none)</option>
                {textFields.map((f) => <option key={f}>{f}</option>)}
              </select>
            </div>
            <div className="field-map-group">
              <label>Description</label>
              <select value={descField} onChange={(e) => setDescField(e.target.value)}>
                <option>(none)</option>
                {textFields.map((f) => <option key={f}>{f}</option>)}
              </select>
            </div>
            <div className="field-map-group">
              <label>Image</label>
              <select value={imgField} onChange={(e) => setImgField(e.target.value)}>
                <option>(none)</option>
                {allFields.map((f) => <option key={f}>{f}</option>)}
              </select>
            </div>
          </div>
          </div>

          {/* Metadata chips */}
          {allFields.length > 0 && (
            <div className="meta-section">
              <div className="sec-label">Metadata</div>
              <div className="meta-chips">
                {allFields.map((f) => (
                  <button
                    key={f}
                    className={`meta-chip ${hiddenFields.has(f) ? "" : "selected"}`}
                    onClick={() => toggleHiddenField(f)}
                    title={hiddenFields.has(f) ? `${f} (hidden — click to show)` : `${f} (click to hide)`}
                  >{f}</button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      <section className={`search-panel ${activeTemplate === "agent" && agenticMode === "chat" ? "chat-layout" : ""}`}>
            {/* Search bar and suggestions — hidden in chat mode */}
            {!(activeTemplate === "agent" && agenticMode === "chat") && (
            <>
            <div className="search-row">
              <div className="query-wrap">
                <span className="query-icon">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
                  </svg>
                </span>
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") { setAutocompleteOptions([]); runSearch(query); } }}
                  placeholder={activeTemplate === "agent" ? "Ask a question..." : "Search..."}
                />
                {autocompleteOptions.length > 0 && (
                  <div className="autocomplete-menu">
                    {autocompleteOptions.map((option) => (
                      <button key={option} type="button" className="autocomplete-option"
                        onMouseDown={(e) => e.preventDefault()} onClick={() => onAutocompleteOptionClick(option)}>
                        {option}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <button className="search-btn" onClick={() => runSearch(query)} disabled={loading}>
                {loading ? "..." : "Search"}
              </button>
            </div>

            {/* Suggestions */}
            <div className="suggestions">
              <div className="chips">
                {(activeTemplate === "agent"
                  ? (agentPrompts.search.length > 0 ? agentPrompts.search : (agentPromptsLoaded ? AGENT_PROMPTS_FALLBACK.search : [])).map((text) => ({ text, capability: "" }))
                  : suggestions.slice(0, 5)
                ).map((item) => (
                    <button key={`${item.text}-${item.capability || "none"}`} className="chip" onClick={() => {
                      if (activeTemplate === "agent") { setQuery(item.text); runSearch(item.text); }
                      else onSuggestionClick(item);
                    }}>
                      <span>{item.text}</span>
                      {item.capability && (
                        <span className={`cap-badge cap-${item.capability}`}>
                          {(capabilityLabel[item.capability] || item.capability).toUpperCase()}
                        </span>
                      )}
                    </button>
                  ))}
                </div>
            </div>
            </>
            )}

            {/* Results area: comparison view or standard single-index results */}
            {comparisonEnabled ? (
              <ComparisonView
                query={query}
                searchSize={searchSize}
                activeTemplate={activeTemplate}
                schema={schema}
                fieldOverrides={fieldOverrides}
                filterSource={filterSource}
                compareIndex1={compareIndex1}
                compareIndex2={compareIndex2}
              />
            ) : (
              <>
                {/* Status row — only shown after a search has been performed */}
                {(activeTemplate !== "agent" || agenticMode === "search") && results.length > 0 && (
                <div className="status-row">
                  <span>{stats}</span>
                  {queryMode && <span>mode: {queryMode}</span>}
                  {capability && <span>capability: {capability}</span>}
                  {activeTemplate !== "agent" && !error && <span>semantic: {usedSemantic ? "on" : "off"}</span>}
                  {error && <span className="error">{error}</span>}
                </div>
                )}

                {/* Agentic fallback warning — shown when agentic search failed or backend lacks agentic support */}
                {activeTemplate === "agent" && !loading && results.length > 0 && !ragAnswer && !agentStepsSummary && !dslQuery && (
                  <div className="agentic-fallback-warning">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                    <span>AI agent unavailable — showing standard search results.
                      {fallbackReason && fallbackReason.includes("expired") && " AWS credentials may have expired."}
                      {fallbackReason && fallbackReason.includes("timeout") && " The request timed out."}
                    </span>
                  </div>
                )}

                {/* Loading bar - hidden in agent chat mode (has typing indicator) */}
                {loading && (activeTemplate !== "agent" || agenticMode === "search") && (
                  <div className="loading-container">
                    <div className="loading-bar"><div className="loading-bar-progress"></div></div>
                    <div className="loading-text">Searching...</div>
                  </div>
                )}

                {/* Template-specific results */}
                {activeTemplate === "agent" && agenticMode === "chat" && (
                  <div className="chat-messages-area">
                    {chatMessages.length > 0 && (
                      <div className="chat-toolbar">
                        <button className="new-chat-btn" onClick={() => { setChatMessages([]); setMemoryId(null); }}>
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
                          New conversation
                        </button>
                      </div>
                    )}
                    <AgenticChat messages={chatMessages} loading={loading} onPromptClick={(text) => { setQuery(text); runSearch(text); }} agentPrompts={agentPrompts} agentPromptsLoaded={agentPromptsLoaded} schema={schema} />
                    <div className="chat-input-bar">
                      <div className="query-wrap">
                        <span className="query-icon">
                          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
                          </svg>
                        </span>
                        <input
                          value={query}
                          onChange={(e) => setQuery(e.target.value)}
                          onKeyDown={(e) => { if (e.key === "Enter") { setAutocompleteOptions([]); runSearch(query); } }}
                          placeholder="Ask a question..."
                        />
                      </div>
                      <button className="search-btn" onClick={() => runSearch(query)} disabled={loading}>
                        {loading ? "..." : "Send"}
                      </button>
                    </div>
                  </div>
                )}
                {activeTemplate === "agent" && agenticMode === "search" && (
                  <>
                    {!loading && results.length === 0 && !ragAnswer && !error && (
                      <div className="chat-empty">
                        <div className="chat-empty-icon">
                          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" style={{opacity: 0.3}}>
                            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
                          </svg>
                        </div>
                        <div className="chat-empty-title">Agentic Search</div>
                        <div className="chat-empty-desc">Ask questions in natural language. The AI agent will decompose your query and find relevant results.</div>
                        <div className="chat-empty-examples">
                          Try: "Show me the most relevant results" or "Find items from the last 5 years"
                        </div>
                      </div>
                    )}
                    {ragAnswer && (
                      <div className="rag-answer-card">
                        <div className="rag-answer-text">{renderChatText(ragAnswer)}</div>
                      </div>
                    )}
                    {(agentStepsSummary || dslQuery) && results.length > 0 && (
                      <div className="search-reasoning-bar">
                        {agentStepsSummary && (
                          <details className="chat-agent-reasoning">
                            <summary>Agent reasoning</summary>
                            <div className="chat-reasoning-content">
                              <div className="chat-reasoning-section">
                                <pre className="chat-reasoning-pre">{agentStepsSummary}</pre>
                              </div>
                            </div>
                          </details>
                        )}
                        {dslQuery && (
                          <details className="chat-agent-reasoning">
                            <summary>Generated DSL</summary>
                            <div className="chat-reasoning-content">
                              <div className="chat-reasoning-section">
                                <pre className="chat-reasoning-pre">{(() => { try { return JSON.stringify(JSON.parse(dslQuery), null, 2); } catch(e) { return dslQuery; } })()}</pre>
                              </div>
                            </div>
                          </details>
                        )}
                      </div>
                    )}
                    {results.length > 0 && <DocumentResults results={results} loading={loading} filterSource={filterSource} schema={schema} fieldOverrides={fieldOverrides} />}
                  </>
                )}
                {activeTemplate === "document" && (
                  <>
                    {ragAnswer && (
                      <div className="rag-answer-card">
                        <div className="rag-answer-text">{renderChatText(ragAnswer)}</div>
                      </div>
                    )}
                    <DocumentResults results={results} loading={loading} filterSource={filterSource} schema={schema} fieldOverrides={fieldOverrides} />
                  </>
                )}
                {(activeTemplate === "ecommerce" || activeTemplate === "media") && (
                  <EcommerceResults results={results} loading={loading} schema={schema} fieldOverrides={fieldOverrides} filterSource={filterSource} />
                )}
              </>
            )}
      </section>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);