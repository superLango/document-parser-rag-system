type PlaceholderProps = {
  title: string;
  description: string;
};

export default function Placeholder({ title, description }: PlaceholderProps) {
  return (
    <section className="page">
      <header className="page-head">
        <h1>{title}</h1>
        <p>{description}</p>
      </header>
      <div className="empty-state">
        <span>M0 骨架</span>
        <p>业务功能将在后续里程碑接入。</p>
      </div>
    </section>
  );
}
