const ORIGIN = "https://skillaz-digest.up.railway.app";

function isPublicRead(pathname, method) {
  return ["GET", "HEAD"].includes(method) && (
    pathname === "/" ||
    pathname === "/digests" ||
    pathname.startsWith("/digest/") ||
    pathname.startsWith("/static/") ||
    pathname.startsWith("/uploads/")
  );
}

function isReviewFlow(pathname, method) {
  return ["GET", "HEAD", "POST"].includes(method) && (
    pathname.startsWith("/review/") ||
    pathname.startsWith("/auth/")
  );
}

export default {
  async fetch(request) {
    const incoming = new URL(request.url);

    if (
      !isPublicRead(incoming.pathname, request.method) &&
      !isReviewFlow(incoming.pathname, request.method)
    ) {
      return new Response("Not found", { status: 404 });
    }

    const target = new URL(incoming.pathname + incoming.search, ORIGIN);
    const headers = new Headers(request.headers);
    headers.delete("authorization");
    headers.delete("host");
    headers.set("x-forwarded-host", incoming.host);
    headers.set("x-forwarded-proto", "https");

    const upstreamRequest = new Request(target, request);
    const upstream = await fetch(new Request(upstreamRequest, {
      headers,
      redirect: "manual",
    }));

    const responseHeaders = new Headers(upstream.headers);
    responseHeaders.set("x-releasecraft-proxy", "cloudflare");

    const location = responseHeaders.get("location");
    if (location?.startsWith(ORIGIN)) {
      responseHeaders.set("location", incoming.origin + location.slice(ORIGIN.length));
    }

    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: responseHeaders,
    });
  },
};
