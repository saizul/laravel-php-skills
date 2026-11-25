<?php

namespace Tests\Unit;

use PHPUnit\Framework\Attributes\Test;
use PHPUnit\Framework\TestCase;

class MoneyTest extends TestCase
{
    #[Test]
    public function it_adds(): void
    {
        $this->assertSame(3, 1 + 2);
    }

    public function test_formats(): void
    {
        expect(number_format(1234.5, 2))->toBe('1,234.50');
    }
}
