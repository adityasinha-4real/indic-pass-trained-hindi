import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Don't regenerate AGENTS.md/CLAUDE.md scaffolding files on every dev
  // server start -- this app isn't using either, and the research repo
  // keeps its own documentation conventions (see ../docs/).
  agentRules: false,
};

export default nextConfig;
