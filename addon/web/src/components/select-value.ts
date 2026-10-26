/**
 * Give each `<select data-value>` under `root` its value. Call it from `updated()`: on the first render Lit sets a
 * select's own bindings before its options exist, so a `.value` binding alone would leave the first option chosen.
 */
export function applySelectValues(root: ParentNode): void {
  for (const select of root.querySelectorAll<HTMLSelectElement>("select[data-value]")) {
    const value = select.dataset.value ?? "";
    if (select.value !== value) select.value = value;
  }
}
