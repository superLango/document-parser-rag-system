import { BookOpenText, Check } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { PageHeader } from '@/components/PageHeader'
import { helpSections } from '@/content/help'

export default function HelpPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="系统"
        title="帮助文档"
        description="当前已开发功能的使用说明与操作截图，将随开发持续完善"
      />

      <div className="grid gap-6 xl:grid-cols-2">
        {helpSections.map((section) => (
          <Card key={section.id} interactive className="animate-fade-up overflow-hidden">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <BookOpenText className="h-4 w-4 text-primary" />
                {section.title}
              </CardTitle>
              <p className="text-sm text-muted-foreground">{section.description}</p>
            </CardHeader>
            <CardContent className="space-y-4">
              {section.image ? (
                <div className="overflow-hidden rounded-xl border border-border bg-muted/40">
                  <img
                    src={section.image}
                    alt={section.title}
                    className="h-auto w-full object-cover"
                    loading="lazy"
                  />
                </div>
              ) : null}
              <ol className="space-y-2">
                {section.steps.map((step, index) => (
                  <li key={index} className="flex items-start gap-2 text-sm">
                    <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-primary-strong">
                      <Check className="h-3 w-3" />
                    </span>
                    <span className="leading-5 text-muted-foreground">{step}</span>
                  </li>
                ))}
              </ol>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
