export default function DealsTable({ deals, columns }) {
  return (
    <table>
      <thead>
        <tr>
          {columns.map((c) => (
            // `numeric` right-aligns the column and lines its digits up in a
            // tabular face, so amounts can be compared down the column by eye
            // instead of read one at a time.
            <th key={c.key} className={c.numeric ? 'col-num' : undefined}>{c.header}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {deals.map((d) => (
          <tr key={d.sheet_key || d.opportunity_id}>
            {columns.map((c) => (
              <td key={c.key} className={c.numeric ? 'col-num' : undefined}>{c.render(d)}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
