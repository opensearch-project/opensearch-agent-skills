const { useEffect, useState, useRef, useCallback } = React;

const TEMPLATES = [
  { id: "document", label: "Document" },
  { id: "ecommerce", label: "E-Commerce" },
  { id: "agentic-chat", label: "Conversational", disabled: true },
  { id: "media", label: "Media", disabled: true },
];

function TemplateIcon({ id }) {
  const size = 32;
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
  if (id === "agentic-chat") {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
      </svg>
    );
  }
  if (id === "media") {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>
      </svg>
    );
  }
  return null;
}

// ---------------------------------------------------------------------------
// Field role inference for ecommerce/media templates
// ---------------------------------------------------------------------------
const TITLE_HINTS = ["title", "name", "label", "heading", "subject"];
const IMAGE_HINTS = ["image", "img", "poster", "photo", "thumbnail", "picture", "cover", "avatar", "logo"];
const DESC_HINTS = ["description", "summary", "overview", "abstract", "content", "body", "text", "plot"];

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

    if (!roles.title && TITLE_HINTS.some((h) => lower.includes(h)) && strVal.length < 200) {
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
      } else if (!roles.description && strVal.length > 40) {
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
              <div className="ecommerce-title">{roles.title?.value || item.preview || item.id}</div>
              {roles.description && (
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
function DocumentResults({ results, loading, filterSource }) {
  if (loading) return null;
  const maxScore = results.length > 0 ? Math.max(...results.map((r) => Number(r.score || 0)), 0.001) : 1;
  return (
    <div className="results doc-results">
      {results.map((item, idx) => {
        const pct = Math.round((Number(item.score || 0) / maxScore) * 100);
        return (
          <article className="doc-card" key={item.id || idx} style={{ animationDelay: `${idx * 35}ms` }}>
            <div className="doc-score-col">
              <div className="doc-score-bar-bg">
                <div className="doc-score-bar-fill" style={{ height: `${pct}%` }} />
              </div>
              <span className="doc-score-label">{Number(item.score || 0).toFixed(2)}</span>
            </div>
            <div className="doc-content">
              <div className="doc-id">ID: {item.id || "(none)"}</div>
              <details>
                <summary>Full document</summary>
                <pre>{JSON.stringify(filterSource ? filterSource(item.source) : item.source, null, 2)}</pre>
              </details>
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
function generateChatSummary(query, results, total) {
  if (!results || results.length === 0) {
    return `I couldn't find any results matching "${query}". Try rephrasing your question or using different keywords.`;
  }

  const count = total ?? results.length;
  const topItems = results.slice(0, 5);

  // Build a natural summary
  let summary = `I found ${count} result${count !== 1 ? "s" : ""} for your query. `;

  if (count <= 3) {
    summary += `Here's what I found:\n\n`;
  } else {
    summary += `Here are the top matches:\n\n`;
  }

  topItems.forEach((item, i) => {
    const s = item.source || {};
    const title = s.title || s.name || s.primaryTitle || s.label || item.preview || "Untitled";
    const year = s.year || s.startYear || "";
    const desc = s.plot || s.description || s.overview || s.summary || item.preview || "";
    const score = Number(item.score || 0);
    const rating = s.rating ? ` \u2022 Rating: ${s.rating}` : "";
    const genre = s.genre || s.genres || "";
    const genreStr = genre ? ` \u2022 ${genre}` : "";

    summary += `${i + 1}. **${title}**`;
    if (year) summary += ` (${year})`;
    summary += `${genreStr}${rating}`;
    if (score > 0) summary += ` \u2022 Relevance: ${score.toFixed(2)}`;
    summary += `\n`;
    if (desc && desc !== title) {
      const shortDesc = desc.length > 150 ? desc.slice(0, 147) + "..." : desc;
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

function AgenticChat({ messages, loading }) {
  const endRef = useRef(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
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
          <div className="chat-empty-desc">Ask questions in natural language. I'll search the index and summarize what I find.</div>
          <div className="chat-empty-examples">
            Try: "Show me sci-fi movies rated above 8" or "What are the best films by Christopher Nolan?"
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
                  <div className="chat-summary">
                    {renderChatText(msg.summary || generateChatSummary(msg.query, msg.results, msg.total))}
                  </div>
                  <div className="chat-meta-bar">
                    <span>{msg.total ?? msg.results.length} result(s) \u2022 {msg.took_ms ?? 0}ms</span>
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
// Comparison Toggle
// ---------------------------------------------------------------------------
function ComparisonToggle({ enabled, onToggle }) {
  return (
    <div className="compare-toggle">
      <span className="compare-toggle-label">Compare</span>
      <div
        role="switch"
        aria-checked={enabled}
        aria-label="Toggle comparison mode"
        tabIndex={0}
        className={`compare-toggle-track ${enabled ? "on" : ""}`}
        onClick={() => onToggle(!enabled)}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggle(!enabled); } }}
      >
        <div className="compare-toggle-thumb" />
      </div>
    </div>
  );
}


// ---------------------------------------------------------------------------
// ResultPane – one half of the comparison view
// ---------------------------------------------------------------------------
function ResultPane({ label, indexName, results, loading, error, stats, queryMode, capability, usedSemantic, fallbackReason, activeTemplate, schema, fieldOverrides, filterSource }) {
  const capabilityLabel = {
    exact: "Exact",
    semantic: "Semantic",
    structured: "Structured",
    combined: "Combined",
    autocomplete: "Autocomplete",
    fuzzy: "Fuzzy",
    manual: "Manual",
  };

  const isSecond = label === "Index 2";

  return (
    <div className="result-pane">
      {/* Header */}
      <div className={`result-pane-header ${isSecond ? "idx2" : "idx1"}`}>
        <span className={`result-pane-label ${isSecond ? "idx2" : "idx1"}`}>{label}</span>
        <span className="result-pane-index">{indexName}</span>
      </div>

      {/* Status row */}
      <div className="result-pane-status">
        <span>{stats}</span>
        {queryMode && <span>mode: {queryMode}</span>}
        {capability && <span>capability: {capabilityLabel[capability] || capability}</span>}
        {!error && <span>semantic: {usedSemantic ? "on" : "off"}</span>}
        {fallbackReason && <span>fallback: {fallbackReason}</span>}
      </div>

      {/* Loading indicator */}
      {loading && (
        <div className="result-pane-loading">
          <div className="loading-bar"><div className="loading-bar-progress"></div></div>
          <span className="loading-text">Searching...</span>
        </div>
      )}

      {/* Error message */}
      {error && (
        <div className="result-pane-error">{error}</div>
      )}

      {/* Results */}
      {!loading && !error && (
        <div className="result-pane-results">
          {activeTemplate === "ecommerce" || activeTemplate === "media" ? (
            <EcommerceResults results={results} loading={false} schema={schema} fieldOverrides={fieldOverrides} filterSource={filterSource} />
          ) : (
            <DocumentResults results={results} loading={false} filterSource={filterSource} />
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
  const [showSuggestions, setShowSuggestions] = useState(true);
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
  const [chatMessages, setChatMessages] = useState([]);
  const [showSettings, setShowSettings] = useState(false);

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

  // ---- Schema fetch ----
  const fetchSchema = useCallback(async (index) => {
    if (!index) return;
    try {
      const res = await fetch(`/api/schema?index=${encodeURIComponent(index)}`);
      const data = await res.json();
      if (!data.error) {
        setSchema(data);
        setActiveTemplate(data.suggested_template || "document");
      }
    } catch (_) {}
  }, []);

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

  // ---- Search ----
  const runSearch = async (overrideQuery = null, options = {}) => {
    // In comparison mode, ComparisonView handles search via its own useEffect on query
    if (comparisonEnabled) return;
    const effectiveQuery = (overrideQuery !== null ? overrideQuery : query).trim();
    const effectiveIndex = indexName.trim();
    const effectiveSize = parseInt(searchSize, 10) || 20;
    if (!effectiveIndex) { setError("Please enter an index name."); return; }

    setError("");
    setLoading(true);

    if (activeTemplate === "agentic-chat" && effectiveQuery) {
      setChatMessages((prev) => [...prev, { role: "user", text: effectiveQuery }]);
    }

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
        if (activeTemplate === "agentic-chat") {
          setChatMessages((prev) => [...prev, { role: "assistant", error: data.error, results: [], total: 0, took_ms: 0 }]);
        }
      } else {
        const hits = Array.isArray(data.hits) ? data.hits : [];
        setResults(hits);
        setStats(`Loaded ${data.total ?? 0} hit(s) in ${data.took_ms ?? 0} ms`);
        setQueryMode(String(data.query_mode || ""));
        setCapability(String(data.capability || ""));
        setFallbackReason(String(data.fallback_reason || ""));
        setUsedSemantic(Boolean(data.used_semantic));
        if (activeTemplate === "agentic-chat") {
          setChatMessages((prev) => [...prev, {
            role: "assistant", results: hits, total: data.total, took_ms: data.took_ms,
            capability: data.capability, query: effectiveQuery, error: null,
          }]);
        }
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

  const isChat = activeTemplate === "agentic-chat";

  // Derive field lists from schema for field mapping dropdowns
  const allFields = schema?.field_specs ? Object.keys(schema.field_specs).filter((f) => !f.endsWith(".keyword")) : [];
  const textFields = (schema?.field_categories?.text || []);
  const keywordFields = new Set(schema?.field_categories?.keyword || []);

  return (
    <div className={`shell template-${activeTemplate}`}>
      <header className="topbar">
        <div className="brand">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 42.6667 42.6667" fill="none" aria-label="OpenSearch" role="img">
            <path fill="#075985" d="M41.1583 15.6667C40.3252 15.6667 39.6499 16.342 39.6499 17.1751C39.6499 29.5876 29.5876 39.6499 17.1751 39.6499C16.342 39.6499 15.6667 40.3252 15.6667 41.1583C15.6667 41.9913 16.342 42.6667 17.1751 42.6667C31.2537 42.6667 42.6667 31.2537 42.6667 17.1751C42.6667 16.342 41.9913 15.6667 41.1583 15.6667Z"/>
            <path fill="#082F49" d="M32.0543 25.3333C33.5048 22.967 34.9077 19.8119 34.6317 15.3947C34.06 6.24484 25.7726 -0.696419 17.9471 0.0558224C14.8835 0.350311 11.7379 2.84747 12.0173 7.32032C12.1388 9.26409 13.0902 10.4113 14.6363 11.2933C16.1079 12.1328 17.9985 12.6646 20.1418 13.2674C22.7308 13.9956 25.7339 14.8135 28.042 16.5144C30.8084 18.553 32.6994 20.9162 32.0543 25.3333Z"/>
            <path fill="#075985" d="M2.6124 9.33333C1.16184 11.6997 -0.241004 14.8548 0.0349954 19.2719C0.606714 28.4218 8.89407 35.3631 16.7196 34.6108C19.7831 34.3164 22.9288 31.8192 22.6493 27.3463C22.5279 25.4026 21.5765 24.2554 20.0304 23.3734C18.5588 22.5339 16.6681 22.0021 14.5248 21.3992C11.9358 20.6711 8.93276 19.8532 6.62463 18.1522C3.85831 16.1136 1.96728 13.7505 2.6124 9.33333Z"/>
          </svg>
          OpenSearch
        </div>
        <div className="divider"></div>
        <div className="title">Search Builder</div>
        <div className="topbar-right">
          {comparisonAvailable && (
            <ComparisonToggle
              enabled={comparisonEnabled}
              onToggle={(on) => {
                if (on) {
                  setComparisonEnabled(true);
                  setResults([]);
                  setError("");
                  setStats("Ready");
                  // Prefill dropdowns if not already set
                  if (!compareIndex1 || !compareIndex2) {
                    const current = indexName.trim();
                    const names = availableIndices.map((i) => i.name);
                    const other = names.find((n) => n !== current) || "";
                    if (!compareIndex1) setCompareIndex1(current || names[0] || "");
                    if (!compareIndex2) setCompareIndex2(other || names[1] || "");
                  }
                } else {
                  setComparisonEnabled(false);
                  if (compareIndex2) {
                    setIndexName(compareIndex2);
                    loadSuggestions(compareIndex2);
                    fetchSchema(compareIndex2);
                  }
                }
              }}
            />
          )}
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
          {/* Index / Size row */}
          <div className="idx-row">
            <div className="field-group">
              <label>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>
                </svg>
                {comparisonEnabled ? "Index 1" : "Index"}
              </label>
              {availableIndices.length > 0 ? (
                <select
                  className="idx-input"
                  value={comparisonEnabled ? compareIndex1 : indexName}
                  onChange={(e) => {
                    if (comparisonEnabled) {
                      setCompareIndex1(e.target.value);
                    } else {
                      setIndexName(e.target.value);
                      loadSuggestions(e.target.value);
                      fetchSchema(e.target.value);
                    }
                  }}
                >
                  <option value="">Select index...</option>
                  {availableIndices.map((idx) => (
                    <option key={idx.name} value={idx.name}>{idx.name} ({idx.docs} docs)</option>
                  ))}
                </select>
              ) : (
                <input className="idx-input" value={indexName} onChange={(e) => setIndexName(e.target.value)} placeholder="e.g. movies-index" />
              )}
            </div>
            {comparisonEnabled && (
              <div className="field-group">
                <label className="idx2-label">Index 2</label>
                <select
                  className="idx-input"
                  value={compareIndex2}
                  onChange={(e) => { setCompareIndex2(e.target.value); loadSuggestions(e.target.value); fetchSchema(e.target.value); }}
                >
                  <option value="">Select index...</option>
                  {availableIndices.map((idx) => (
                    <option key={idx.name} value={idx.name}>{idx.name} ({idx.docs} docs)</option>
                  ))}
                </select>
              </div>
            )}
            <div className="field-group">
              <label>Size</label>
              <input className="size-input" value={searchSize} onChange={(e) => setSearchSize(e.target.value)} />
            </div>
            <div className="spacer"></div>
            {schema && (
              <span className="schema-caps">
                {schema.capabilities.map((c) => (
                  <span key={c} className={`cap-pill cap-${c}`}>{c}</span>
                ))}
              </span>
            )}
          </div>

          <hr className="sep" />

          {/* Template selection */}
          <div className="sec-label">Template</div>
          <div className="tpl-grid">
            {TEMPLATES.map((t) => {
              const disabled = !!t.disabled;
              return (
                <button
                  key={t.id}
                  className={`tpl-card ${activeTemplate === t.id ? "on" : ""} ${disabled ? "disabled" : ""}`}
                  disabled={disabled}
                  title=""
                  onClick={() => {
                    if (disabled) return;
                    setActiveTemplate(t.id);
                    if (t.id === "agentic-chat") setChatMessages([]);
                  }}
                >
                  <div className="tpl-card-icon"><TemplateIcon id={t.id} /></div>
                  <div className="tpl-card-label">{t.label}</div>
                  {schema?.suggested_template === t.id && <span className="template-auto">auto</span>}
                </button>
              );
            })}
          </div>

          <hr className="sep" />

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

      <section className="search-panel">
        {/* Agentic chat template */}
        {isChat ? (
          <div className="chat-container">
            <AgenticChat messages={chatMessages} loading={loading} />
            <div className="chat-input-row">
              <input
                className="chat-input"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && query.trim()) { runSearch(); setQuery(""); } }}
                placeholder="Ask a question..."
              />
              <button className="search-btn" onClick={() => { if (query.trim()) { runSearch(); setQuery(""); } }} disabled={loading}>
                {loading ? "..." : "Send"}
              </button>
            </div>
          </div>
        ) : (
          <>
            {/* Standard search bar */}
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
                  onKeyDown={(e) => { if (e.key === "Enter") { setAutocompleteOptions([]); runSearch(); } }}
                  placeholder="Search..."
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
              <button className="search-btn" onClick={() => runSearch()} disabled={loading}>
                {loading ? "..." : "Search"}
              </button>
            </div>

            {/* Suggestions */}
            <div className="suggestions">
              <button className="suggestion-toggle" onClick={() => setShowSuggestions(!showSuggestions)}>
                Try these auto-generated queries
                <span>{showSuggestions ? "\u25B4" : "\u25BE"}</span>
              </button>
              {showSuggestions && (
                <div className="chips">
                  {suggestions.map((item) => (
                    <button key={`${item.text}-${item.capability || "none"}`} className="chip" onClick={() => onSuggestionClick(item)}>
                      <span>{item.text}</span>
                      {item.capability && (
                        <span className={`cap-badge cap-${item.capability}`}>
                          {(capabilityLabel[item.capability] || item.capability).toUpperCase()}
                        </span>
                      )}
                      {item.query_mode && item.query_mode !== "default" && (
                        <span className="mode-badge">{item.query_mode.toUpperCase()}</span>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>

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
                {/* Status row */}
                <div className="status-row">
                  <span>{stats}</span>
                  {queryMode && <span>mode: {queryMode}</span>}
                  {capability && <span>capability: {capability}</span>}
                  {!error && <span>semantic: {usedSemantic ? "on" : "off"}</span>}
                  {fallbackReason && <span>fallback: {fallbackReason}</span>}
                  {error && <span className="error">{error}</span>}
                </div>

                {/* Loading bar */}
                {loading && (
                  <div className="loading-container">
                    <div className="loading-bar"><div className="loading-bar-progress"></div></div>
                    <div className="loading-text">Searching...</div>
                  </div>
                )}

                {/* Template-specific results */}
                {(activeTemplate === "ecommerce" || activeTemplate === "media") && (
                  <EcommerceResults results={results} loading={loading} schema={schema} fieldOverrides={fieldOverrides} filterSource={filterSource} />
                )}
                {activeTemplate === "document" && <DocumentResults results={results} loading={loading} filterSource={filterSource} />}
              </>
            )}
          </>
        )}
      </section>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
