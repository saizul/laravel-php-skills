<?php

namespace Tests\Feature;

use App\Models\Invoice;
use Tests\TestCase;

class InvoiceTest extends TestCase
{
    public function test_invoice_page_loads(): void
    {
        $invoice = Invoice::factory()->create();
        $this->getJson('/api/invoices/42');
    }

    /** @test */
    public function it_marks_paid(): void
    {
        $this->assertDatabaseHas('invoices', ['paid' => true]);
    }

    public function test_skipped(): void
    {
        $this->markTestSkipped('flaky');
    }

    public function helper(): void
    {
        // dd() inside a comment is fine
    }
}
