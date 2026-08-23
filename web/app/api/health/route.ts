import { NextResponse } from "next/server";

export async function GET() {
  return NextResponse.json({
    status: "ok",
    supabase_url_configured: Boolean(process.env.NEXT_PUBLIC_SUPABASE_URL),
    supabase_anon_key_configured: Boolean(process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY),
  });
}
