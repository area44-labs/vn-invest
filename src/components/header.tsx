import { Sun, Moon } from "lucide-react";

import { useTheme } from "@/hooks/use-theme";
import { cn } from "@/lib/utils";

interface HeaderProps {
  currentView: "dashboard" | "stock" | "history";
  onNavigate: (view: "dashboard" | "stock" | "history") => void;
  lastUpdated?: string;
}

export function Header({ currentView, onNavigate, lastUpdated }: HeaderProps) {
  const { theme, toggleTheme } = useTheme();

  return (
    <header className="sticky top-0 z-40 w-full border-b border-border bg-background/90 backdrop-blur-md transition-colors">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        {/* Report Identity & Navigation */}
        <div className="flex items-center space-x-6">
          <button
            onClick={() => onNavigate("dashboard")}
            className="cursor-pointer font-mono text-sm font-bold tracking-tight text-foreground uppercase hover:opacity-80"
          >
            VN Invest
          </button>

          <nav className="flex items-center space-x-2 font-mono text-xs">
            <button
              onClick={() => onNavigate("dashboard")}
              className={cn(
                "cursor-pointer rounded-sm px-2.5 py-1 transition-colors",
                currentView === "dashboard"
                  ? "bg-primary font-bold text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              Dashboard
            </button>
            <button
              onClick={() => onNavigate("history")}
              className={cn(
                "cursor-pointer rounded-sm px-2.5 py-1 transition-colors",
                currentView === "history"
                  ? "bg-primary font-bold text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              Lịch Sử
            </button>
          </nav>
        </div>

        {/* Right navigation items */}
        <div className="flex items-center space-x-4">
          {lastUpdated && (
            <div className="hidden items-center font-mono text-[11px] tracking-tight text-muted-foreground md:flex">
              <span className="mr-2 h-1.5 w-1.5 rounded-full bg-trend-up-text" />
              Cập nhật: <span className="ml-1 font-semibold text-foreground">{lastUpdated}</span>
            </div>
          )}

          <div className="flex items-center space-x-2">
            <button
              onClick={toggleTheme}
              className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-sm border border-border bg-background text-muted-foreground transition-all hover:bg-accent hover:text-accent-foreground focus:outline-none"
              title={theme === "light" ? "Chuyển sang chế độ tối" : "Chuyển sang chế độ sáng"}
              aria-label="Toggle theme"
            >
              {theme === "light" ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
            </button>

            <a
              href="https://github.com/area44-labs/vn-invest"
              target="_blank"
              rel="noopener noreferrer"
              className="flex h-8 w-8 cursor-pointer items-center justify-center rounded-sm border border-border bg-background text-muted-foreground transition-all hover:bg-accent hover:text-accent-foreground focus:outline-none"
              title="GitHub Repository"
              aria-label="GitHub Repository"
            >
              <svg className="h-4 w-4 fill-current" viewBox="0 0 24 24" aria-hidden="true">
                <path
                  fillRule="evenodd"
                  clipRule="evenodd"
                  d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"
                />
              </svg>
            </a>
          </div>
        </div>
      </div>
    </header>
  );
}
