import { useQuery } from '@tanstack/react-query'
import { CheckCircle2, Clock3, FileUp, Layers, Sparkles } from 'lucide-react'
import { modulesApi } from '@/api/modules/modules'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { PageHeader } from '@/components/PageHeader'
import { Skeleton } from '@/components/ui/skeleton'

export default function ModulePlaceholderPage({ moduleKey }: { moduleKey: string }) {
  const { data: module, isLoading } = useQuery({
    queryKey: ['module', moduleKey],
    queryFn: () => modulesApi.get(moduleKey),
  })

  if (isLoading || !module) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-20 w-full rounded-2xl" />
        <Skeleton className="h-64 w-full rounded-2xl" />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="功能模块"
        title={module.name}
        description={module.summary}
        actions={
          <Badge variant="warning" dot>
            规划中
          </Badge>
        }
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="gap-2 text-base">
              <Layers className="h-4 w-4 text-primary" />
              能力说明
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm leading-6 text-muted-foreground">{module.description}</p>
            <div className="flex flex-wrap gap-2">
              {module.input_types.map((type) => (
                <Badge key={type} variant="outline">
                  {type}
                </Badge>
              ))}
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              {module.highlights.map((item) => (
                <div
                  key={item}
                  className="flex items-center gap-2 rounded-lg border border-border/70 bg-background-soft/60 px-3 py-2 text-sm"
                >
                  <CheckCircle2 className="h-4 w-4 shrink-0 text-primary" />
                  {item}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="gap-2 text-base">
              <Sparkles className="h-4 w-4 text-primary" />
              上线计划
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-start gap-2 rounded-lg border border-amber-100 bg-amber-50/60 px-3 py-2.5">
              <Clock3 className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
              <div>
                <p className="text-sm font-medium text-amber-800">该功能正在规划中</p>
                <p className="mt-0.5 text-xs leading-5 text-amber-700/80">
                  解析模板与字段规则仍在设计，暂不开放上传与解析。
                </p>
              </div>
            </div>
            <Button disabled className="w-full gap-1.5">
              <FileUp className="h-4 w-4" />
              上传文件（规划中）
            </Button>
            <p className="text-xs leading-5 text-muted-foreground">
              如需提前试用，请联系平台管理员评估文件样本与字段清单。
            </p>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
