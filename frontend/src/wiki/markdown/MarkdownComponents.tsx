import type { Components } from "react-markdown";

import { MermaidBlock } from "../mermaid/MermaidBlock";

export const markdownComponents: Components = {
  a({ href, children, ...props }) {
    if (href === "source-link") {
      return <>{children}</>;
    }
    const isExternal = href?.startsWith("http://") || href?.startsWith("https://");
    return (
      <a {...props} href={href} target={isExternal ? "_blank" : props.target} rel={isExternal ? "noreferrer" : props.rel}>
        {children}
      </a>
    );
  },
  code({ className, children, ...props }) {
    const language = /language-(\w+)/.exec(className ?? "")?.[1];
    const code = String(children).replace(/\n$/, "");
    if (language === "mermaid") {
      return <MermaidBlock chart={code} />;
    }
    return (
      <code className={className} {...props}>
        {children}
      </code>
    );
  }
};

export function wikiMarkdownComponents(onSelectPage: (slug: string) => void): Components {
  return {
    ...markdownComponents,
    a({ href, children, ...props }) {
      if (href === "source-link") {
        return <>{children}</>;
      }
      const internalSlug = wikiPageSlugFromHref(href);
      if (internalSlug) {
        return (
          <a
            {...props}
            href={`#wiki-${internalSlug}`}
            onClick={(event) => {
              event.preventDefault();
              onSelectPage(internalSlug);
            }}
          >
            {children}
          </a>
        );
      }
      const isExternal = href?.startsWith("http://") || href?.startsWith("https://");
      return (
        <a {...props} href={href} target={isExternal ? "_blank" : props.target} rel={isExternal ? "noreferrer" : props.rel}>
          {children}
        </a>
      );
    }
  };
}

function wikiPageSlugFromHref(href: string | undefined): string | null {
  if (!href) {
    return null;
  }
  if (href.startsWith("wiki-page:")) {
    return href.slice("wiki-page:".length);
  }
  const wikiPathMatch = /^\/wiki\/[^/]+\/([^/#?]+)$/.exec(href);
  return wikiPathMatch?.[1] ?? null;
}
