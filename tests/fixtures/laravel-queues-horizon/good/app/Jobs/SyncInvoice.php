<?php

namespace App\Jobs;

use Illuminate\Contracts\Queue\ShouldQueue;
use Illuminate\Foundation\Queue\Queueable;
use Throwable;

class SyncInvoice implements ShouldQueue
{
    use Queueable;

    public int $tries = 5;
    public int $timeout = 30;
    public array $backoff = [10, 60, 300];

    public function handle(): void
    {
    }

    public function failed(?Throwable $e): void
    {
    }
}
