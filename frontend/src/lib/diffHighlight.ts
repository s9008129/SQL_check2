import { StateField, type Extension, type Range } from "@codemirror/state";
import { Decoration, type DecorationSet, EditorView } from "@codemirror/view";
import type { DiffLineTag } from "./sqlDiff";

/**
 * Builds a static CodeMirror extension that shades whole lines according
 * to a 1-based line-number -> tag map (see lib/sqlDiff.ts). The map is
 * fixed for the lifetime of the EditorView it's attached to — SqlCompare
 * recreates the view (via SqlEditor's `extraExtensions` dependency) rather
 * than mutating this field, since a read-only compare pane's content never
 * changes after the AI result arrives.
 */
export function diffHighlightExtension(lineClasses: ReadonlyMap<number, DiffLineTag>): Extension {
  return StateField.define<DecorationSet>({
    create(state) {
      const ranges: Range<Decoration>[] = [];
      for (let lineNo = 1; lineNo <= state.doc.lines; lineNo++) {
        const tag = lineClasses.get(lineNo);
        if (!tag) continue;
        const line = state.doc.line(lineNo);
        ranges.push(Decoration.line({ class: `cm-diff-${tag}` }).range(line.from));
      }
      return Decoration.set(ranges, true);
    },
    update(value) {
      return value;
    },
    provide: (field) => EditorView.decorations.from(field),
  });
}
