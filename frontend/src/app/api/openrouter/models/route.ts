type OpenRouterModelRecord = {
  id: string;
  name: string;
  context_length: number;
  pricing?: { prompt?: string; completion?: string };
};

export async function GET() {
  try {
    const url = new URL("https://openrouter.ai/api/v1/models");
    url.searchParams.set("output_modalities", "text");
    url.searchParams.set("supported_parameters", "temperature");
    url.searchParams.set("sort", "most-popular");

    const response = await fetch(url, {
      headers: { Accept: "application/json" },
      next: { revalidate: 3600 },
    });
    if (!response.ok) {
      return Response.json({ detail: `OpenRouter model catalog returned ${response.status}.` }, { status: 502 });
    }

    const payload = await response.json() as { data?: OpenRouterModelRecord[] };
    const models = (payload.data || []).filter((model) => typeof model.id === "string" && typeof model.name === "string").map((model) => ({
      id: model.id,
      name: model.name,
      contextLength: model.context_length,
      inputPricePerMillion: pricePerMillion(model.pricing?.prompt),
      outputPricePerMillion: pricePerMillion(model.pricing?.completion),
    }));
    return Response.json({ models, updatedAt: new Date().toISOString() }, { headers: { "Cache-Control": "public, max-age=300, stale-while-revalidate=3600" } });
  } catch {
    return Response.json({ detail: "Could not reach the OpenRouter model catalog." }, { status: 502 });
  }
}

function pricePerMillion(price?: string) {
  if (!price) return null;
  const value = Number(price);
  return Number.isFinite(value) ? value * 1_000_000 : null;
}
