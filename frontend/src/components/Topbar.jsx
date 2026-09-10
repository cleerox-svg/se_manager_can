export default function Topbar({ title, sub }) {
  return (
    <div className="topbar">
      <div>
        <h1 id="page-title">{title}</h1>
        {sub && <div className="sub">{sub}</div>}
      </div>
    </div>
  );
}
