import { useEffect, useRef } from "react";
import { EditorState, type Extension } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { basicSetup } from "codemirror";
import { sql, PLSQL } from "@codemirror/lang-sql";

export interface SqlEditorProps {
  value: string;
  onChange?: (value: string) => void;
  readOnly?: boolean;
  /** "light" matches the input textarea look; "dark" matches the SQL-compare panes. */
  variant?: "light" | "dark";
  minHeightPx?: number;
  ariaLabel?: string;
  /** Extra CodeMirror extensions, e.g. diff-highlight decorations (see lib/sqlDiff.ts). */
  extraExtensions?: Extension[];
}

// Stable reference so components that omit extraExtensions don't force a
// CodeMirror remount on every render (a fresh `[]` literal as a default
// parameter value would compare unequal to itself across renders).
const EMPTY_EXTENSIONS: Extension[] = [];

const lightTheme = EditorView.theme({
  "&": {
    fontSize: "13px",
    backgroundColor: "#fbfcff",
    color: "#172033",
  },
  ".cm-content": {
    fontFamily: '"SFMono-Regular", Consolas, "Liberation Mono", monospace',
    padding: "13px 14px",
    caretColor: "#172033",
  },
  ".cm-gutters": {
    backgroundColor: "#fbfcff",
    color: "#a7b0c0",
    border: "none",
  },
  "&.cm-focused": { outline: "none" },
  ".cm-scroller": { overflow: "auto", lineHeight: "1.55" },
});

const darkTheme = EditorView.theme(
  {
    "&": {
      fontSize: "12px",
      backgroundColor: "transparent",
      color: "#d7e0ef",
    },
    ".cm-content": {
      fontFamily: '"SFMono-Regular", Consolas, "Liberation Mono", monospace',
      padding: "16px",
      caretColor: "#d7e0ef",
    },
    ".cm-gutters": {
      backgroundColor: "transparent",
      color: "#5b6577",
      border: "none",
    },
    "&.cm-focused": { outline: "none" },
    ".cm-scroller": { overflow: "auto", lineHeight: "1.65" },
  },
  { dark: true },
);

/**
 * CodeMirror 6 host, controlled via a `value` prop like a normal React
 * input. Used both as the editable SQL input (InputPanel) and as the two
 * read-only compare panes (SqlCompare) with an Oracle/PL-SQL-ish language
 * mode (PRD §38.1 "CodeMirror 6").
 */
export default function SqlEditor({
  value,
  onChange,
  readOnly = false,
  variant = "light",
  minHeightPx = 200,
  ariaLabel,
  extraExtensions = EMPTY_EXTENSIONS,
}: SqlEditorProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const viewRef = useRef<EditorView | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    const updateListener = EditorView.updateListener.of((update) => {
      if (update.docChanged && onChangeRef.current) {
        onChangeRef.current(update.state.doc.toString());
      }
    });

    const state = EditorState.create({
      doc: value,
      extensions: [
        basicSetup,
        sql({ dialect: PLSQL }),
        EditorView.lineWrapping,
        EditorView.editable.of(!readOnly),
        EditorState.readOnly.of(readOnly),
        variant === "dark" ? darkTheme : lightTheme,
        updateListener,
        ...extraExtensions,
      ],
    });

    const view = new EditorView({ state, parent: host });
    viewRef.current = view;
    if (ariaLabel) {
      view.contentDOM.setAttribute("aria-label", ariaLabel);
    }

    return () => {
      view.destroy();
      viewRef.current = null;
    };
    // Only remount CodeMirror when the editor's *shape* changes (editable
    // vs read-only, theme, or the diff-highlight extensions). Plain text
    // edits flow through the dispatch effect below so typing stays smooth.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readOnly, variant, extraExtensions]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const current = view.state.doc.toString();
    if (current !== value) {
      view.dispatch({ changes: { from: 0, to: current.length, insert: value } });
    }
  }, [value]);

  return (
    <div
      ref={hostRef}
      className={`editor-host ${variant === "dark" ? "editor-host-dark" : "editor-host-light"}`}
      style={{ minHeight: minHeightPx }}
    />
  );
}
