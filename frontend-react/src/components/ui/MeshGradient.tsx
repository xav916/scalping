export function MeshGradient() {
  return (
    <div
      aria-hidden
      className="pointer-events-none fixed inset-0 -z-10"
      style={{
        background: `
          radial-gradient(ellipse 600px 300px at 15% 10%, rgba(139,92,246,0.18), transparent 60%),
          radial-gradient(ellipse 500px 300px at 85% 90%, rgba(236,72,153,0.12), transparent 60%),
          radial-gradient(ellipse 500px 200px at 50% 50%, rgba(34,211,238,0.08), transparent 60%)
        `,
      }}
    />
  );
}
