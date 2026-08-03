import Brain from "./Brain";

export function generateStaticParams() {
  return [{ slug: [] }];
}

export default function BrainPage() {
  return <Brain />;
}
