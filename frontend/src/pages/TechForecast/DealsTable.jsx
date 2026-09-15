export default function DealsTable({ deals, columns }) {
  return (
    <table>
      <thead>
        <tr>
          {columns.map((c) => (
            <th key={c.key}>{c.header}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {deals.map((d) => (
          <tr key={d.sheet_key || d.opportunity_id}>
            {columns.map((c) => (
              <td key={c.key}>{c.render(d)}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
