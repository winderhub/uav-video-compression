# Linux 服务器视频压缩指南

## 概览

Linux 脚本用于服务器批量压缩和夜间调度，保留两种处理模式：

- 输出到独立目录，保留源文件。
- 在源目录内压缩并替换原文件。

第一次处理一批数据时，优先使用独立输出模式。

## 依赖

运行前确认系统提供：

- Bash
- FFmpeg 和 ffprobe
- GNU xargs
- `flock`
- tmux，只有夜间调度需要
- cron，只有定时启动和停止需要

项目现有服务器环境曾使用 FFmpeg 4.4.2、tmux 3.2a、GNU xargs 4.8.0 和 `flock` 2.37.2 完成验证。2026-08-17 已使用 40 个真实 MP4 副本完成原位端到端验证。

## 固定编码参数

```text
编码器：       libx264
编码速度：     preset fast
质量：         CRF 18
像素格式：     yuv420p
容器优化：     +faststart
音频：         不保留
输入流：       只处理第一路视频流
```

CRF 18 是高质量有损压缩。脚本会丢弃音频、DJI `djmd`/`dbgi` 私有数据流和其他附加视频流，只保留第一路视频和部分容器级 metadata。

## 推荐模式：输出到独立目录

```bash
cd /path/to/uav-video-compression

./compression/batch_compress_raw_videos.sh \
  "/path/to/源视频目录" \
  "/path/to/压缩后视频目录" \
  2
```

三个参数依次是源目录、输出目录和并发数。并发数省略时默认为 3。

输出目录保留源目录内部的相对结构，并生成：

```text
输出目录/
├── 原有目录结构和压缩视频
├── _logs/
├── _reports/
└── broken_sources.txt
```

输出目录不能位于源目录内部，否则扫描可能再次发现刚生成的文件。

如果目标视频已经存在，且 ffprobe 检测到的视频包数与源文件一致，脚本会跳过；包数不同时会重新编码。

## 原位压缩

只有在确认备份、权限和磁盘空间后，才使用原位模式：

```bash
cd /path/to/uav-video-compression

./compression/batch_compress_in_place.sh \
  "/path/to/待压缩视频目录" \
  2
```

两个参数依次是视频根目录和并发数。并发数省略时默认为 8；共享服务器上建议明确使用 1 或 2。

每个文件的处理流程：

```text
ffprobe 检查源文件
  → 在源文件旁生成 *.compress_tmp.MP4
  → FFmpeg 重编码
  → 校验源文件和临时文件的视频包数
  → mv 替换原文件
  → 写入 done.txt
```

临时文件和原文件位于同一文件系统。编码或校验失败时，原文件不会被替换。

## 原位任务状态

默认状态目录：

```text
~/tmp/video_compression/
└── inplace_meta/<源路径标识>/
    ├── done.txt
    ├── broken_sources.txt
    ├── logs/
    └── reports/
```

可以通过环境变量指定其他状态目录：

```bash
VIDEO_COMPRESSION_STATE_DIR="$HOME/tmp/my_video_state" \
  ./compression/batch_compress_in_place.sh "/path/to/待压缩目录" 2
```

查看各任务完成数量：

```bash
find "$HOME/tmp/video_compression/inplace_meta" \
  -name done.txt -exec wc -l {} \;
```

`done.txt` 中已经记录的路径不会再次处理。如果需要使用不同参数重新压缩，必须使用新的状态目录，并先确认不会造成二次有损压缩。

## 70 Mbps 跳过规则

原位脚本把视频码率低于 70 Mbps 的文件视为“疑似已经压缩”，写入 `done.txt` 后跳过。该规则可以防止重复压缩，也可能误跳过原本就是低码率的原始视频。

正式处理前应抽样检查输入码率：

```bash
ffprobe -v error -select_streams v:0 \
  -show_entries stream=codec_name,width,height,bit_rate \
  -of default=noprint_wrappers=1 \
  "/path/to/sample.MP4"
```

## 压缩报告

脚本正常收尾时会生成 TSV 报告。即使部分视频失败，汇总仍会通过 `run_exit_code` 标明本次运行是否存在错误。

独立输出模式：

```text
<输出目录>/_reports/compression_report_<时间>_<进程号>.tsv
```

原位模式：

```text
~/tmp/video_compression/inplace_meta/<源路径标识>/reports/
```

报告包含处理状态、输入输出路径、码率、体积、节省空间、失败原因和总体汇总。

格式化查看：

```bash
column -s $'\t' -t < "/path/to/compression_report.tsv" | less -S
```

只查看汇总：

```bash
grep '^#' "/path/to/compression_report.tsv"
```

原位模式中的 `SKIPPED_DONE` 表示文件在此前运行中已经完成。由于源文件已经被替换，本次无法重新得到其压缩前指标，因此该行不会计入本次总体积。

主脚本被 `SIGKILL`、服务器掉电或终端强制终止时，可能留下没有 SUMMARY 的部分报告。

## 可选运行指标

直接运行压缩脚本不会启动资源采样。需要诊断耗时或资源占用时，使用包装器：

```bash
cd /path/to/uav-video-compression

VIDEO_COMPRESSION_STATE_DIR="$HOME/tmp/my_video_state" \
  ./tools/run_with_metrics.sh \
  "$HOME/tmp/my_video_metrics" \
  "in_place_test" \
  -- ./compression/batch_compress_in_place.sh "/path/to/待压缩目录" 1
```

前两个参数是指标输出目录和运行标签，`--` 后面是原压缩命令。默认每 5 秒采样一次，可通过 `VIDEO_COMPRESSION_METRICS_INTERVAL` 调整。

输出包括：

- `run_summary_*.txt`：总耗时、退出码和资源汇总。
- `stage_summary_*.tsv`：各处理阶段汇总。
- `phase_events_*.tsv`：逐视频阶段明细。
- `resource_samples_*.tsv`：进程树和系统资源采样。
- `time_verbose_*.txt`：GNU `time -v` 输出。
- `command_*.log`：完整命令输出。

当前 `libx264` 编码使用 CPU，正常情况下进程树 GPU 显存应为 0。系统级 GPU 数据可能包含其他用户的任务。

## 夜间调度

脚本不保存真实数据路径。运行前设置：

```bash
export VIDEO_COMPRESSION_SOURCE_DIR="/path/to/待压缩目录"
export VIDEO_COMPRESSION_JOBS=1
```

可选变量 `VIDEO_COMPRESSION_SESSION` 用于修改 tmux 会话名，默认是 `video_compression_nightly`。

手动启动：

```bash
./scheduling/nightly_start.sh
```

查看后台任务：

```bash
tmux attach -t video_compression_nightly
```

按 `Ctrl-b`，再按 `d`，可以退出 tmux 界面但保持任务运行。

停止任务并清理未完成临时文件：

```bash
./scheduling/nightly_stop.sh
```

### 配置 cron

不要在未核对路径和资源占用时直接安装 cron 任务。

```bash
mkdir -p "$HOME/tmp/video_compression/nightly_logs"
crontab -e
```

示例：

```cron
0 23 * * * VIDEO_COMPRESSION_SOURCE_DIR="/path/to/待压缩目录" VIDEO_COMPRESSION_JOBS=1 /path/to/uav-video-compression/scheduling/nightly_start.sh >> "$HOME/tmp/video_compression/nightly_logs/cron_stderr.log" 2>&1
0 9 * * * VIDEO_COMPRESSION_SOURCE_DIR="/path/to/待压缩目录" /path/to/uav-video-compression/scheduling/nightly_stop.sh >> "$HOME/tmp/video_compression/nightly_logs/cron_stderr.log" 2>&1
```

安装后使用 `crontab -l` 单独检查。

## 上线前检查

1. 输入和输出路径没有写反。
2. 独立输出目录不在源目录内部。
3. 已抽样确认视频码率、编码和附加数据流。
4. 可以接受删除音频及 DJI 私有数据流。
5. NAS 有足够空间保存当前并发任务的临时文件。
6. 并发数适合共享服务器负载。
7. 原位模式的数据已有备份或可以重新获取。
8. 夜间调度的目标目录确实是本次任务目录。

## 使用限制

- 不要对同一源目录同时运行多个任务。`done.txt` 不是严格的跨进程锁。
- 独立输出模式要求源文件和结果的视频包数严格相等。
- 原位模式允许视频包数相差不超过 50。
- 视频包数校验能发现明显失败，但不等于逐帧完整解码，也不能证明画面质量符合业务要求。
- 原位任务中断后，已记录到 `done.txt` 的文件会跳过；未完成的临时文件会在下次处理时删除并重建。
